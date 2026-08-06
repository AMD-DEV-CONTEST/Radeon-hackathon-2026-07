from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from glass_gateway.domain.meeting import StoredEvidence
from glass_gateway.services.event_memory_projection import build_event_message
from glass_gateway.services.identity_candidates import IdentityCandidateAggregator
from glass_gateway.services.media_converter import MediaConverter
from glass_gateway.services.memory_review_store import MemoryReviewStore
from glass_gateway.services.speech_presence import failed_presence_result
from glass_gateway.services.window_asr import WindowASRProcessor


class EverOSMemoryAPI(Protocol):
    async def add_messages(self, session_id: str, messages: list[dict]) -> dict: ...

    async def flush(self, session_id: str) -> dict: ...


class AudioTranscriber(Protocol):
    async def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str: ...


class SpeechPresenceDetector(Protocol):
    async def analyze(
        self,
        pcm_bytes: bytes,
        sample_rate: int,
        *,
        window_id: str,
        audio_evidence_refs: list[str],
    ) -> dict[str, Any]: ...


class IdentityRecognizer(Protocol):
    async def recognize_window(self, **kwargs) -> dict[str, list[dict[str, Any]]]: ...


class SceneInterpreter(Protocol):
    async def interpret_window(self, **kwargs) -> dict[str, Any]: ...


class EventContextStabilizer(Protocol):
    async def stabilize_window(self, **kwargs) -> dict[str, Any]: ...

    async def repair_pending(self, **kwargs) -> list[dict[str, Any]]: ...

    async def summarize_event_queue(
        self,
        queue: dict[str, Any],
        *,
        next_window: dict[str, Any] | None = None,
    ) -> tuple[dict[str, str], dict[str, Any]]: ...


class ObjectPerceptionHints(Protocol):
    async def hints_for_evidence(
        self,
        evidence_ids: list[str],
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]: ...


class ObjectCardInterpreter(Protocol):
    async def process_window(self, **kwargs) -> dict[str, Any]: ...


class CommitmentExtractorAPI(Protocol):
    async def process_window(self, **kwargs) -> dict[str, Any]: ...


class EverOSCapsuleBridge:
    """Continuous memory bridge for V2.

    It stores raw evidence locally, writes aligned 30s-ish capsules into one
    EverOS boot session, and only keeps bridge-local projections. EverOS owns
    long-term memory extraction and aggregation.
    """

    def __init__(
        self,
        *,
        raw_media_root: str | Path,
        converter: MediaConverter,
        everos: EverOSMemoryAPI,
        review_store: MemoryReviewStore,
        user_id: str,
        sender_name: str,
        audio_transcriber: AudioTranscriber | None = None,
        speech_presence_detector: SpeechPresenceDetector | None = None,
        identity_recognizer: IdentityRecognizer | None = None,
        scene_interpreter: SceneInterpreter | None = None,
        object_perception: ObjectPerceptionHints | None = None,
        object_card_interpreter: ObjectCardInterpreter | None = None,
        commitment_extractor: CommitmentExtractorAPI | None = None,
        event_context_stabilizer: EventContextStabilizer | None = None,
        transcription_chunk_bytes: int = 64 * 1024 * 1024,
        asr_full_window_enabled: bool = True,
        asr_tail_guard_ms: int = 5000,
        asr_fallback_speech_probability: float = 0.50,
        flush_interval_ms: int = 5 * 60 * 1000,
        retry_interval_ms: int = 60 * 1000,
    ) -> None:
        self.root = Path(raw_media_root).resolve()
        self.converter = converter
        self.everos = everos
        self.review_store = review_store
        self.user_id = user_id
        self.sender_name = sender_name
        self.audio_transcriber = audio_transcriber
        self.window_asr = (
            WindowASRProcessor(
                audio_transcriber,
                method_version="m2-vad-gated-full-window-tail-v1",
                transcribe_full_window=asr_full_window_enabled,
                tail_guard_ms=asr_tail_guard_ms,
            )
            if audio_transcriber is not None
            else None
        )
        self.asr_fallback_speech_probability = max(
            0.0, min(1.0, float(asr_fallback_speech_probability))
        )
        self.speech_presence_detector = speech_presence_detector
        self.identity_recognizer = identity_recognizer
        self.scene_interpreter = scene_interpreter
        self.object_perception = object_perception
        self.object_card_interpreter = object_card_interpreter
        self.commitment_extractor = commitment_extractor
        self.event_context_stabilizer = event_context_stabilizer
        self.transcription_chunk_bytes = transcription_chunk_bytes
        self.flush_interval_ms = flush_interval_ms
        self.retry_interval_ms = max(1000, retry_interval_ms)
        self._retry_task: asyncio.Task[None] | None = None
        self._manifest_locks: dict[str, asyncio.Lock] = {}

    async def close_window(
        self,
        *,
        session_id: str,
        user_id: str,
        sender_name: str,
        audio_chunks: list[StoredEvidence],
        images: list[StoredEvidence],
        sample_rate: int,
        image_width: int,
        image_height: int,
        window_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not audio_chunks:
            raise ValueError("cannot build a capsule window without audio")

        manifest_path = self.root / user_id / session_id / "capsule-manifest.json"
        existing_manifest = self._load_manifest(manifest_path)
        if existing_manifest.get("state") in {"skipped", "checkpointed"}:
            return self._replay_result(
                manifest_path=manifest_path,
                manifest=existing_manifest,
                submission=self._submission_result(existing_manifest),
            )
        if existing_manifest.get("message") and existing_manifest.get("state") in {
            "pending",
            "added",
            "flushed",
        }:
            submission = await self._submit_manifest(manifest_path, existing_manifest)
            if self._manifest_needs_retry(self._load_manifest(manifest_path)):
                self._schedule_retry()
            return self._replay_result(
                manifest_path=manifest_path,
                manifest=self._load_manifest(manifest_path),
                submission=submission,
            )

        captured_at_ms = min(item.captured_at_ms for item in audio_chunks)
        duration_ms = max(
            item.captured_at_ms + max(0, item.duration_ms)
            for item in audio_chunks
        ) - captured_at_ms
        boot_key = str(
            (window_metadata or {}).get("boot_session_key")
            or self._boot_key_from_window_id(session_id)
        )
        boot_session = await asyncio.to_thread(
            self.review_store.current_boot_session,
            user_id=user_id,
            captured_at_ms=captured_at_ms,
            boot_key=boot_key,
        )
        boot_session_id = str(boot_session["id"])
        wav = await asyncio.to_thread(
            self.converter.pcm_chunks_to_wav,
            user_id,
            session_id,
            audio_chunks,
            sample_rate=sample_rate,
        )
        pcm_bytes = await asyncio.to_thread(self._audio_bytes, audio_chunks)
        audio_evidence_refs = [item.evidence_id for item in audio_chunks]
        audio_presence = await self._analyze_audio_presence(
            window_id=session_id,
            pcm_bytes=pcm_bytes,
            sample_rate=sample_rate,
            audio_evidence_refs=audio_evidence_refs,
        )
        speech_segments = audio_presence.get("speech_segments") or []
        presence_completed = audio_presence.get("status") == "completed"
        asr_eligible = (
            presence_completed
            and audio_presence.get("presence_class") in {"speech", "mixed"}
        )
        fallback_eligible = (
            presence_completed
            and audio_presence.get("presence_class") == "environment_sound"
            and float(audio_presence.get("speech_probability") or 0.0)
            >= self.asr_fallback_speech_probability
            and float(audio_presence.get("speech_probability") or 0.0)
            > float(audio_presence.get("music_probability") or 0.0)
        )
        asr_eligible = asr_eligible or fallback_eligible
        if not asr_eligible:
            transcription_status = WindowASRProcessor.not_requested(
                window_id=session_id,
                reason=(
                    f"presence_{audio_presence.get('presence_class')}"
                    if audio_presence.get("status") == "completed"
                    else "presence_failed"
                ),
                audio_evidence_refs=audio_evidence_refs,
                presence_run_id=audio_presence.get("presence_run_id"),
                speech_segments=speech_segments,
            )
        elif self.window_asr is None:
            transcription_status = WindowASRProcessor.unavailable(
                window_id=session_id,
                audio_evidence_refs=audio_evidence_refs,
                presence_run_id=audio_presence.get("presence_run_id"),
                speech_segments=speech_segments,
            )
        else:
            asr_pcm_bytes, asr_sample_rate = await asyncio.to_thread(
                self.converter.wav_to_pcm, wav
            )
            transcription_status = await self.window_asr.process(
                window_id=session_id,
                pcm_bytes=asr_pcm_bytes,
                sample_rate=asr_sample_rate,
                speech_segments=speech_segments,
                audio_evidence_refs=audio_evidence_refs,
                presence_run_id=audio_presence.get("presence_run_id"),
            )
            transcription_status["gate_mode"] = (
                "high_probability_environment_fallback"
                if fallback_eligible
                else "vad_speech_present"
            )
            transcription_status["presence_class"] = audio_presence.get(
                "presence_class"
            )
            if fallback_eligible:
                transcription_status.setdefault("warnings", []).append(
                    "high_probability_environment_fallback"
                )
        transcript = str(transcription_status.get("transcript") or "")
        prepared_images = self._prepare_images(images, image_width=image_width, image_height=image_height)
        clock = self._window_clock(
            window_metadata=window_metadata,
            audio_chunks=audio_chunks,
            captured_at_ms=captured_at_ms,
        )
        source_evidence = {
            "audio_chunks": [self._stored_evidence_manifest(item) for item in audio_chunks],
            "images": [self._stored_evidence_manifest(item) for item in images],
        }
        technical_window = dict(window_metadata or {})
        technical_window.update(
            {
                "window_id": session_id,
                "boot_session_key": boot_key,
                "boot_session_id": boot_session_id,
                "start_local": clock["window_started_at_local"],
                "end_local": clock["window_ended_at_local"],
                "derived_audio_uri": wav.uri,
                "representative_image_refs": [item.get("id") for item in prepared_images],
            }
        )
        evidence_status = dict(technical_window.get("evidence_status") or {})
        evidence_status.setdefault("audio", "present")
        evidence_status.setdefault("image", "present" if prepared_images else "missing")
        evidence_status.setdefault("missing_modalities", [] if prepared_images else ["image"])
        technical_window["evidence_status"] = evidence_status
        technical_window["audio_presence"] = audio_presence
        object_perception_task = asyncio.create_task(
            self._collect_object_perception(prepared_images)
        )
        evidence = [
            {
                "id": "window-audio",
                "kind": "audio",
                "uri": wav.uri,
                "captured_at_ms": captured_at_ms,
                "ended_at_ms": max(item.captured_at_ms for item in audio_chunks),
                "timezone_name": clock["timezone_name"],
                "source_chunk_ids": [item.evidence_id for item in audio_chunks],
            },
            *[{"kind": "image", **image} for image in prepared_images],
        ]
        if transcript and transcription_status.get("asr_run_id"):
            evidence.append(
                {
                    "id": str(transcription_status["asr_run_id"]),
                    "kind": "asr",
                    "captured_at_ms": captured_at_ms,
                    "status": transcription_status.get("status"),
                }
            )
        recognized = await self._recognize_identities(
            boot_session_id=boot_session_id,
            window_id=session_id,
            captured_at_ms=captured_at_ms,
            wav_uri=wav.uri,
            wav_path=str(wav.path),
            transcript=transcript,
            images=prepared_images,
            audio_chunks=audio_chunks,
            sample_rate=sample_rate,
            speech_present=bool(audio_presence.get("speech_present")),
            asr_result=transcription_status,
        )
        identity_projection = IdentityCandidateAggregator(self.review_store).ingest_window(
            boot_session_id=boot_session_id,
            window_id=session_id,
            captured_at_ms=captured_at_ms,
            visible_people=recognized["visible_people"],
            audio_speakers=recognized["audio_speakers"],
        )
        visible_people = identity_projection["visible_people"]
        audio_speakers = identity_projection["audio_speakers"]
        identity_perception = recognized.get("identity_perception") or {
            "status": "not_requested"
        }
        voice_perception = recognized.get("voice_perception") or {
            "status": "not_requested"
        }
        capsule_id = self._capsule_id(boot_session_id, session_id)
        commitment_task = asyncio.create_task(
            self._extract_commitments(
                window_id=session_id,
                capsule_id=capsule_id,
                captured_at_ms=captured_at_ms,
                transcript=transcript,
                audio_speakers=audio_speakers,
                evidence_refs=[
                    str(item.get("id") or item.get("uri") or "")
                    for item in evidence
                    if item.get("id") or item.get("uri")
                ],
            )
        )
        interpretation = await self._interpret_scene(
            window_id=session_id,
            captured_at_ms=captured_at_ms,
            duration_ms=duration_ms,
            wav_uri=wav.uri,
            wav_path=str(wav.path),
            transcript=transcript,
            evidence=evidence,
            images=prepared_images,
            visible_people=visible_people,
            audio_speakers=audio_speakers,
            technical_window=technical_window,
        )
        object_perception = await object_perception_task
        technical_window["object_perception"] = object_perception
        interpretation_succeeded = (
            interpretation.get("status") == "completed"
            and interpretation.get("contract_valid") is not False
        )
        capsule_text = (
            str(interpretation.get("first_person_caption") or "").strip()
            if interpretation_succeeded
            else ""
        )
        window_interpretation = {
            **interpretation,
            "window_id": session_id,
            "captured_at_ms": captured_at_ms,
            "duration_ms": duration_ms,
            "first_person_caption": capsule_text,
            "evidence_refs": list(
                interpretation.get("evidence_refs")
                or [str(item.get("id")) for item in evidence if item.get("id")]
            ),
            "evidence_status": evidence_status,
            "asr": transcription_status,
        }
        stabilized_projection = await self._stabilize_context(
            boot_session_id=boot_session_id,
            window_id=session_id,
            captured_at_ms=captured_at_ms,
            window_interpretation=window_interpretation,
        )
        stabilization_completed = stabilized_projection.get("status") == "completed"
        stabilized_caption = str(stabilized_projection.get("corrected_caption") or "").strip()
        everos_caption = (
            stabilized_caption if stabilization_completed and stabilized_caption else capsule_text
        )
        everos_text = self._caption_only_everos_text(everos_caption)
        object_card_result = await self._process_object_cards(
            boot_session_id=boot_session_id,
            window_id=session_id,
            captured_at_ms=captured_at_ms,
            source_capsule_id=capsule_id,
            caption=everos_caption or capsule_text,
            images=prepared_images,
            object_perception=object_perception,
        )
        commitment_result = await commitment_task
        queue_id = str(stabilized_projection.get("event_queue_id") or "")
        window_checkpointed = bool(everos_text and queue_id)
        writeback = (
            {
                "status": "waiting_event_boundary",
                "stage": "event_queue",
                "session_id": boot_session_id,
                "event_queue_id": queue_id,
                "attempt_count": 0,
            }
            if window_checkpointed
            else {
                "status": "skipped",
                "stage": "experience_interpretation",
                "session_id": boot_session_id,
                "attempt_count": 0,
                "reason": (
                    "event_context_stabilizer_unavailable"
                    if everos_text
                    else "first_person_caption_unavailable"
                ),
            }
        )

        audio_presence_runs = self._presence_history(manifest_path, audio_presence)
        asr_runs = self._asr_history(manifest_path, transcription_status)
        manifest = {
            "version": 11,
            "manifest_kind": "capsule_checkpoint",
            "state": "checkpointed" if window_checkpointed else "skipped",
            "boot_session_id": boot_session_id,
            "boot_key": boot_key,
            "window_id": session_id,
            "captured_at_ms": captured_at_ms,
            "event_queue_id": queue_id or None,
            "evidence": evidence,
            "media_uris": [item["uri"] for item in evidence if item.get("uri")],
            "source_evidence": source_evidence,
            "clock": clock,
            "technical_window": technical_window,
            "processing": {
                "identity_perception": identity_perception,
                "voice_perception": voice_perception,
                "object_perception": object_perception,
                "object_cards": {
                    "status": object_card_result.get("status"),
                    "contract_version": object_card_result.get("contract_version"),
                    "candidate_count": object_card_result.get("candidate_count", 0),
                    "schema_errors": object_card_result.get("schema_errors") or [],
                    "latency_ms": object_card_result.get("latency_ms"),
                    "usage": object_card_result.get("usage") or {},
                },
                "commitment_extraction": {
                    "status": commitment_result.get("status"),
                    "contract_version": commitment_result.get("contract_version"),
                    "candidate_count": commitment_result.get("candidate_count", 0),
                    "schema_errors": commitment_result.get("schema_errors") or [],
                },
                "audio_presence": audio_presence,
                "audio_presence_runs": audio_presence_runs,
                "asr": transcription_status,
                "asr_runs": asr_runs,
                "image_preparation": {
                    "status": "completed" if prepared_images else "no_images",
                    "raw_count": len(images),
                    "representative_count": len(prepared_images),
                },
                "scene_interpretation": {
                    "status": interpretation.get("status")
                    or ("completed" if interpretation else "unavailable_or_failed"),
                    "contract_version": interpretation.get("contract_version"),
                    "contract_valid": interpretation.get("contract_valid"),
                    "schema_errors": interpretation.get("schema_errors") or [],
                    "input_usage": interpretation.get("input_usage") or {},
                },
                "experience_interpretation": {
                    "status": interpretation.get("status")
                    or ("completed" if interpretation else "unavailable_or_failed"),
                    "contract_version": interpretation.get("contract_version"),
                    "contract_valid": interpretation.get("contract_valid"),
                    "schema_errors": interpretation.get("schema_errors") or [],
                    "input_usage": interpretation.get("input_usage") or {},
                    "evidence_refs": interpretation.get("evidence_refs") or [],
                },
                "context_stabilization": {
                    "status": stabilized_projection.get("status"),
                    "contract_version": stabilized_projection.get("contract_version"),
                    "contract_valid": stabilized_projection.get("contract_valid"),
                    "schema_errors": stabilized_projection.get("schema_errors") or [],
                    "queue_action": stabilized_projection.get("queue_action"),
                    "event_queue_id": stabilized_projection.get("event_queue_id"),
                    "latency_ms": stabilized_projection.get("latency_ms"),
                    "usage": stabilized_projection.get("usage") or {},
                },
            },
            "transcript": transcript,
            "interpretation": interpretation,
            "window_interpretation": window_interpretation,
            "stabilized_projection": stabilized_projection,
            "flush_due": False,
            "attempt_count": 0,
            "last_attempt_ms": None,
            "last_error": None,
            "everos_writeback": writeback,
        }
        self._write_manifest(manifest_path, manifest)
        submission = self._submission_result(manifest)

        capsule = await asyncio.to_thread(
            self.review_store.add_capsule,
            {
                "id": capsule_id,
                "boot_session_id": boot_session_id,
                "window_id": session_id,
                "captured_at_ms": captured_at_ms,
                "duration_ms": duration_ms,
                "scene": None,
                "activity": None,
                "scene_inference": {},
                "activity_inference": {},
                "observations": [],
                "uncertainties": [],
                "input_usage": interpretation.get("input_usage") or {},
                "interpretation": interpretation,
                "window_interpretation": window_interpretation,
                "stabilized_projection": stabilized_projection,
                "stabilization_status": stabilized_projection.get("status") or "failed",
                "event_queue_id": stabilized_projection.get("event_queue_id"),
                "event_type": "unknown",
                "meeting_likelihood": None,
                "text": capsule_text,
                "visible_people": visible_people,
                "audio_speakers": audio_speakers,
                "identity_perception": identity_perception,
                "voice_perception": voice_perception,
                "objects": [],
                "commitments": commitment_result.get("candidates") or [],
                "evidence": evidence,
                "manifest": str(manifest_path),
                "clock": clock,
                "technical_window": technical_window,
                "evidence_status": evidence_status,
                "audio_presence": audio_presence,
                "audio_presence_runs": audio_presence_runs,
                "asr": transcription_status,
                "asr_runs": asr_runs,
                "everos_writeback": writeback,
            }
        )
        latest_voice = self._latest_voice_projection(session_id)
        if (
            latest_voice.get("status") == "completed"
            and latest_voice.get("audio_speakers")
            and not capsule.get("audio_speakers")
        ):
            refreshed = await asyncio.to_thread(
                self.review_store.update_capsule_voice_projection,
                window_id=session_id,
                audio_speakers=list(latest_voice["audio_speakers"]),
                voice_perception=latest_voice,
            )
            if refreshed is not None:
                capsule = refreshed
        object_observations = list(object_card_result.get("observations") or [])
        meeting_evidence = None
        await asyncio.to_thread(
            self.review_store.touch_boot_session,
            session_id=boot_session_id,
            captured_at_ms=captured_at_ms,
        )
        event_submissions = await self.submit_pending_event_queues(
            boot_session_id=boot_session_id,
        )
        manifest = self._load_manifest(manifest_path)
        manifest["capsule_id"] = capsule["id"]
        self._write_manifest(manifest_path, manifest)
        if self._manifest_needs_retry(manifest):
            self._schedule_retry()
        if stabilized_projection.get("status") == "failed":
            self._schedule_retry()
        return {
            "status": submission["status"],
            "state": submission["state"],
            "everos": submission["everos"],
            "everos_writeback": writeback,
            "media_uris": [item["uri"] for item in evidence if item.get("uri")],
            "manifest": str(manifest_path),
            "boot_session_id": boot_session_id,
            "capsule": capsule,
            "object_observations": object_observations,
            "object_cards": object_card_result,
            "commitment_extraction": commitment_result,
            "meeting_evidence": meeting_evidence,
            "technical_window": technical_window,
            "audio_presence": audio_presence,
            "asr": transcription_status,
            "voice_perception": voice_perception,
            "stabilized_projection": stabilized_projection,
            "event_submissions": event_submissions,
        }

    async def submit_pending_event_queues(
        self,
        *,
        boot_session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        submissions: list[dict[str, Any]] = []
        for queue in self.review_store.sealed_event_queues_pending(
            boot_session_id=boot_session_id,
        ):
            queue_id = str(queue.get("id") or "")
            if not queue_id:
                continue
            session_id = str(queue.get("boot_session_id") or "")
            manifest_path = (
                self.root
                / self.user_id
                / "events"
                / queue_id
                / "event-manifest.json"
            )
            manifest = self._load_manifest(manifest_path)
            if not manifest:
                manifest = {
                    "version": 1,
                    "manifest_kind": "sealed_event",
                    "state": "pending",
                    "event_queue_id": queue_id,
                    "boot_session_id": session_id,
                    "captured_at_ms": int(
                        queue.get("ended_at_ms")
                        or queue.get("updated_at_ms")
                        or queue.get("started_at_ms")
                        or 0
                    ),
                    "source_window_ids": list(queue.get("window_ids") or []),
                    "message": build_event_message(
                        queue,
                        user_id=self.user_id,
                        sender_name=self.sender_name,
                    ),
                    "flush_due": True,
                    "attempt_count": 0,
                    "last_attempt_ms": None,
                    "last_error": None,
                }
                self._write_manifest(manifest_path, manifest)
            submission = await self._submit_manifest(manifest_path, manifest)
            submissions.append(
                {
                    "event_queue_id": queue_id,
                    "manifest": str(manifest_path),
                    **submission,
                }
            )
        if any(
            self._manifest_needs_retry(
                self._load_manifest(Path(item["manifest"]))
            )
            for item in submissions
        ):
            self._schedule_retry()
        return submissions

    async def finalize_open_event(
        self,
        *,
        sealed_at_ms: int,
        reason: str,
        boot_session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not boot_session_id:
            active = self.review_store.active_boot_session(user_id=self.user_id)
            boot_session_id = str(active.get("id") or "") if active else ""
        if not boot_session_id:
            return []
        pending_context = self.review_store.context_pending_entries(
            boot_session_id=boot_session_id,
        )
        if pending_context:
            first_pending = str(pending_context[0].get("window_id") or "unknown")
            raise RuntimeError(
                f"cannot seal event with unresolved context window {first_pending}"
            )
        active = self.review_store.active_event_queue(
            boot_session_id=boot_session_id,
        )
        if active is not None and self.event_context_stabilizer is not None:
            summary_result, _ = await self.event_context_stabilizer.summarize_event_queue(
                active,
            )
            self.review_store.update_active_event_summary(
                boot_session_id=boot_session_id,
                summary=str(summary_result.get("summary") or ""),
            )
        self.review_store.seal_active_event_queue(
            boot_session_id=boot_session_id,
            sealed_at_ms=sealed_at_ms,
            reason=reason,
        )
        return await self.submit_pending_event_queues(
            boot_session_id=boot_session_id,
        )

    async def retry_pending_once(self, *, force: bool = False) -> int:
        retried = await self._retry_context_pending_once()
        manifest_paths = [
            *self.root.glob("*/**/capsule-manifest.json"),
            *self.root.glob("*/**/event-manifest.json"),
        ]
        for manifest_path in sorted(set(manifest_paths)):
            manifest = self._load_manifest(manifest_path)
            if not self._manifest_needs_retry(manifest):
                continue
            if not force and not self._should_retry_manifest(manifest):
                continue
            await self._submit_manifest(manifest_path, manifest)
            retried += 1
        return retried

    async def _retry_context_pending_once(self) -> int:
        stabilizer = self.event_context_stabilizer
        repair = getattr(stabilizer, "repair_pending", None)
        if not callable(repair):
            return 0
        snapshot = self.review_store.snapshot(include_event_entries=True)
        owned_boot_sessions = {
            str(item.get("id") or "")
            for item in snapshot.get("boot_sessions", [])
            if item.get("user_id") == self.user_id
        }
        queue_boot_sessions = [
            str(item.get("boot_session_id") or "")
            for item in snapshot.get("event_queues", [])
            if item.get("status") == "active"
            and item.get("context_pending_entries")
            and str(item.get("boot_session_id") or "") in owned_boot_sessions
        ]
        repaired_count = 0
        for boot_session_id in dict.fromkeys(queue_boot_sessions):
            repaired = await repair(boot_session_id=boot_session_id, limit=32)
            if not isinstance(repaired, list):
                continue
            for item in repaired:
                if not isinstance(item, dict):
                    continue
                window_id = str(item.get("window_id") or "")
                projection = item.get("projection")
                if not window_id or not isinstance(projection, dict):
                    continue
                self._persist_repaired_context_projection(
                    window_id=window_id,
                    projection=projection,
                )
                repaired_count += 1
            if repaired:
                await self.submit_pending_event_queues(
                    boot_session_id=boot_session_id,
                )
        return repaired_count

    def _persist_repaired_context_projection(
        self,
        *,
        window_id: str,
        projection: dict[str, Any],
    ) -> None:
        capsule = self.review_store.update_capsule_context_projection(
            window_id=window_id,
            projection=projection,
        )
        if not capsule:
            return
        manifest_value = str(capsule.get("manifest") or "")
        if not manifest_value:
            return
        manifest_path = Path(manifest_value)
        manifest = self._load_manifest(manifest_path)
        if not manifest:
            return
        event_queue_id = str(projection.get("event_queue_id") or "")
        writeback = {
            "status": "waiting_event_boundary",
            "stage": "event_queue",
            "session_id": str(manifest.get("boot_session_id") or ""),
            "event_queue_id": event_queue_id,
            "attempt_count": 0,
        }
        processing = manifest.setdefault("processing", {})
        processing["context_stabilization"] = {
            "status": projection.get("status"),
            "contract_version": projection.get("contract_version"),
            "contract_valid": projection.get("contract_valid"),
            "schema_errors": projection.get("schema_errors") or [],
            "queue_action": projection.get("queue_action"),
            "event_queue_id": event_queue_id,
            "latency_ms": projection.get("latency_ms"),
            "usage": projection.get("usage") or {},
        }
        manifest["state"] = "checkpointed"
        manifest["event_queue_id"] = event_queue_id
        manifest["stabilized_projection"] = projection
        manifest["everos_writeback"] = writeback
        manifest["last_error"] = None
        self._write_manifest(manifest_path, manifest)

    def start_retry_loop(self) -> None:
        self._schedule_retry()

    async def stop_retry_loop(self) -> None:
        task = self._retry_task
        self._retry_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _schedule_retry(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._retry_task is not None and not self._retry_task.done():
            return
        self._retry_task = loop.create_task(self._retry_pending_loop())

    async def _retry_pending_loop(self) -> None:
        for delay_seconds in (1, 5, 15, 30, 60):
            await asyncio.sleep(delay_seconds)
            await self.retry_pending_once()
        while True:
            await asyncio.sleep(self.retry_interval_ms / 1000)
            await self.retry_pending_once()

    async def _submit_manifest(
        self,
        manifest_path: Path,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        lock = self._manifest_locks.setdefault(str(manifest_path), asyncio.Lock())
        async with lock:
            persisted = self._load_manifest(manifest_path)
            if persisted.get("message"):
                manifest = persisted
            state = str(manifest.get("state") or "pending")
            if state == "flushed" or (state == "added" and not manifest.get("flush_due")):
                result = self._submission_result(manifest)
                self._update_capsule_writeback(manifest, result["writeback"])
                return result

            manifest["last_attempt_ms"] = int(time.time() * 1000)
            manifest["attempt_count"] = int(manifest.get("attempt_count") or 0) + 1
            self._write_manifest(manifest_path, manifest)

            if state == "pending":
                try:
                    add_response = await self.everos.add_messages(
                        str(manifest["boot_session_id"]),
                        [manifest["message"]],
                    )
                except Exception as exc:
                    manifest["state"] = "pending"
                    manifest["last_error"] = self._serialize_error(exc, stage="add")
                    self._write_manifest(manifest_path, manifest)
                    result = self._submission_result(manifest)
                    self._update_capsule_writeback(manifest, result["writeback"])
                    return result
                manifest["state"] = "added"
                manifest["add_response"] = add_response
                manifest["last_error"] = None
                self._write_manifest(manifest_path, manifest)
                state = "added"

            if state == "added" and manifest.get("flush_due"):
                try:
                    flush_response = await self.everos.flush(
                        str(manifest["boot_session_id"]),
                    )
                except Exception as exc:
                    manifest["state"] = "added"
                    manifest["last_error"] = self._serialize_error(exc, stage="flush")
                    self._write_manifest(manifest_path, manifest)
                    result = self._submission_result(manifest)
                    self._update_capsule_writeback(manifest, result["writeback"])
                    return result
                manifest["state"] = "flushed"
                manifest["flush_response"] = flush_response
                manifest["last_error"] = None
                self.review_store.mark_boot_session_flushed(
                    session_id=str(manifest["boot_session_id"]),
                    flushed_at_ms=int(manifest.get("captured_at_ms") or 0),
                )
                self._write_manifest(manifest_path, manifest)

            result = self._submission_result(manifest)
            self._update_capsule_writeback(manifest, result["writeback"])
            return result

    @staticmethod
    def _submission_result(manifest: dict[str, Any]) -> dict[str, Any]:
        state = str(manifest.get("state") or "pending")
        session_id = str(manifest.get("boot_session_id") or "")
        attempt_count = int(manifest.get("attempt_count") or 0)
        if state == "checkpointed":
            writeback = dict(manifest.get("everos_writeback") or {})
            writeback.setdefault("status", "waiting_event_boundary")
            writeback.setdefault("stage", "event_queue")
            writeback.setdefault("session_id", session_id)
            writeback.setdefault("attempt_count", attempt_count)
            return {
                "status": "checkpointed",
                "state": state,
                "everos": {},
                "writeback": writeback,
            }
        if state == "skipped":
            writeback = {
                "status": "skipped",
                "stage": "experience_interpretation",
                "session_id": session_id,
                "attempt_count": attempt_count,
                "reason": "first_person_caption_unavailable",
            }
            return {
                "status": "skipped",
                "state": state,
                "everos": {},
                "writeback": writeback,
            }
        error = manifest.get("last_error") if isinstance(manifest.get("last_error"), dict) else None
        if error:
            writeback = {
                "status": "pending_retry",
                "stage": error.get("stage") or state,
                "session_id": session_id,
                "attempt_count": attempt_count,
                "error": error.get("message") or "EverOS write failed",
                "error_detail": error,
                "add": manifest.get("add_response"),
            }
            return {
                "status": "pending",
                "state": state,
                "everos": {"error": writeback["error"], **error},
                "writeback": writeback,
            }
        if state == "flushed":
            writeback = {
                "status": "flushed",
                "session_id": session_id,
                "attempt_count": attempt_count,
                "add": manifest.get("add_response"),
                "flush": manifest.get("flush_response"),
            }
            return {
                "status": "flushed",
                "state": state,
                "everos": manifest.get("flush_response") or {},
                "writeback": writeback,
            }
        writeback = {
            "status": "added",
            "session_id": session_id,
            "attempt_count": attempt_count,
            "add": manifest.get("add_response"),
        }
        return {
            "status": "added",
            "state": state,
            "everos": manifest.get("add_response") or {},
            "writeback": writeback,
        }

    def _replay_result(
        self,
        *,
        manifest_path: Path,
        manifest: dict[str, Any],
        submission: dict[str, Any],
    ) -> dict[str, Any]:
        processing = manifest.get("processing") if isinstance(manifest.get("processing"), dict) else {}
        return {
            "status": submission["status"],
            "state": submission["state"],
            "everos": submission["everos"],
            "everos_writeback": submission["writeback"],
            "media_uris": list(manifest.get("media_uris") or []),
            "manifest": str(manifest_path),
            "boot_session_id": manifest.get("boot_session_id"),
            "capsule": self.review_store.capsule_for_window(
                str(manifest.get("window_id") or "")
            ),
            "object_observations": [],
            "meeting_evidence": None,
            "technical_window": manifest.get("technical_window") or {},
            "audio_presence": processing.get("audio_presence") or {},
            "asr": processing.get("asr") or {},
            "stabilized_projection": manifest.get("stabilized_projection") or {},
            "idempotent_replay": True,
        }

    def _update_capsule_writeback(
        self,
        manifest: dict[str, Any],
        writeback: dict[str, Any],
    ) -> None:
        event_queue_id = str(manifest.get("event_queue_id") or "")
        if event_queue_id:
            self.review_store.update_event_queue_everos_writeback(
                event_queue_id=event_queue_id,
                writeback=writeback,
            )
            return
        window_id = str(manifest.get("window_id") or "")
        if window_id:
            self.review_store.update_capsule_everos_writeback(
                window_id=window_id,
                writeback=writeback,
            )

    def _should_retry_manifest(self, manifest: dict[str, Any]) -> bool:
        last_attempt_ms = int(manifest.get("last_attempt_ms") or 0)
        if not last_attempt_ms:
            return True
        attempt_count = max(1, int(manifest.get("attempt_count") or 1))
        backoff_ms = min(self.retry_interval_ms, 1000 * (2 ** min(attempt_count - 1, 6)))
        return int(time.time() * 1000) - last_attempt_ms >= backoff_ms

    @staticmethod
    def _manifest_needs_retry(manifest: dict[str, Any]) -> bool:
        state = manifest.get("state")
        if state == "pending":
            return True
        return state == "added" and bool(manifest.get("flush_due"))

    @staticmethod
    def _serialize_error(exc: Exception, *, stage: str) -> dict[str, Any]:
        return {
            "type": type(exc).__name__,
            "message": str(exc),
            "stage": stage,
        }

    def _prepare_images(
        self,
        images: list[StoredEvidence],
        *,
        image_width: int,
        image_height: int,
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for image in self.converter.select_representative_images(images, interval_ms=5000)[:6]:
            if image.media_type in {"image/jpg", "image/jpeg"}:
                prepared.append(
                    {
                        "id": image.evidence_id,
                        "uri": image.path.resolve().as_uri(),
                        **self._capture_fields(image),
                    }
                )
                continue
            if image.media_type == "image/nv12" and image_width > 0 and image_height > 0:
                try:
                    converted = self.converter.nv12_to_jpeg(
                        image,
                        width=image_width,
                        height=image_height,
                    )
                    prepared.append(
                        {
                            "id": image.evidence_id,
                            "uri": converted.uri,
                            **self._capture_fields(image),
                        }
                    )
                    continue
                except Exception:
                    pass
            prepared.append(
                {
                    "id": image.evidence_id,
                    "uri": image.path.resolve().as_uri(),
                    **self._capture_fields(image),
                }
            )
        return prepared

    @staticmethod
    def _capture_fields(item: StoredEvidence) -> dict[str, Any]:
        return {
            "captured_at_ms": item.captured_at_ms,
            "device_monotonic_ms": item.device_monotonic_ms,
            "device_id": item.device_id,
            "boot_id": item.boot_id,
            "stream_id": item.stream_id,
            "sequence": item.sequence,
            "captured_at_device_ms": item.captured_at_device_ms,
            "clock_synced": item.clock_synced,
            "duration_ms": item.duration_ms,
            "clock_anomaly": item.clock_anomaly,
            "clock_deviation_ms": item.clock_deviation_ms,
            "server_received_at_ms": item.server_received_at_ms,
            "server_anchor_ms": item.server_anchor_ms,
            "device_monotonic_anchor_ms": item.device_monotonic_anchor_ms,
            "timezone_name": item.timezone_name,
            "capture_time_source": item.capture_time_source,
        }

    @classmethod
    def _stored_evidence_manifest(cls, item: StoredEvidence) -> dict[str, Any]:
        return {
            "id": item.evidence_id,
            "media_type": item.media_type,
            "path": str(item.path.resolve()),
            "sha256": item.sha256,
            "bytes": item.bytes,
            **cls._capture_fields(item),
        }

    @classmethod
    def _window_clock(
        cls,
        *,
        window_metadata: dict[str, Any] | None,
        audio_chunks: list[StoredEvidence],
        captured_at_ms: int,
    ) -> dict[str, Any]:
        source = dict(window_metadata or {})
        timezone_name = str(
            source.get("timezone_name")
            or audio_chunks[0].timezone_name
            or "Asia/Shanghai"
        )
        ended_at_ms = int(
            source.get("window_ended_at_ms")
            or source.get("end_ms")
            or max(item.captured_at_ms for item in audio_chunks)
        )
        started_at_ms = int(
            source.get("window_started_at_ms")
            or source.get("start_ms")
            or captured_at_ms
        )
        return {
            "authority": "server",
            "time_basis": source.get("time_basis") or "server_anchor_monotonic",
            "timezone_name": timezone_name,
            "server_anchor_ms": source.get("server_anchor_ms") or audio_chunks[0].server_anchor_ms,
            "device_monotonic_anchor_ms": source.get("device_monotonic_anchor_ms")
            if source.get("device_monotonic_anchor_ms") is not None
            else audio_chunks[0].device_monotonic_anchor_ms,
            "window_started_at_ms": started_at_ms,
            "window_ended_at_ms": ended_at_ms,
            "window_started_at_local": cls._local_iso(started_at_ms, timezone_name),
            "window_ended_at_local": cls._local_iso(ended_at_ms, timezone_name),
        }

    @staticmethod
    def _local_iso(epoch_ms: int, timezone_name: str) -> str:
        return datetime.fromtimestamp(
            epoch_ms / 1000,
            tz=ZoneInfo(timezone_name),
        ).isoformat(timespec="milliseconds")

    async def _recognize_identities(
        self,
        *,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        wav_uri: str,
        wav_path: str,
        transcript: str,
        images: list[dict[str, Any]],
        audio_chunks: list[StoredEvidence],
        sample_rate: int,
        speech_present: bool,
        asr_result: dict[str, Any],
    ) -> dict[str, Any]:
        if self.identity_recognizer is None:
            return {
                "visible_people": [],
                "audio_speakers": [],
                "identity_perception": {"status": "not_requested"},
                "voice_perception": {"status": "not_requested"},
            }
        try:
            result = await self.identity_recognizer.recognize_window(
                boot_session_id=boot_session_id,
                window_id=window_id,
                captured_at_ms=captured_at_ms,
                wav_uri=wav_uri,
                wav_path=wav_path,
                transcript=transcript,
                images=images,
                audio_chunks=audio_chunks,
                sample_rate=sample_rate,
                speech_present=speech_present,
                asr_result=asr_result,
            )
        except Exception as exc:
            return {
                "visible_people": [],
                "audio_speakers": [],
                "identity_perception": {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                },
                "voice_perception": {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                },
            }
        return {
            "visible_people": [
                item for item in result.get("visible_people", []) if isinstance(item, dict)
            ],
            "audio_speakers": [
                item for item in result.get("audio_speakers", []) if isinstance(item, dict)
            ],
            "identity_perception": (
                result.get("identity_perception")
                if isinstance(result.get("identity_perception"), dict)
                else {"status": "completed"}
            ),
            "voice_perception": (
                result.get("voice_perception")
                if isinstance(result.get("voice_perception"), dict)
                else {"status": "not_requested"}
            ),
        }

    def _latest_voice_projection(self, window_id: str) -> dict[str, Any]:
        recognizer = self.identity_recognizer
        if recognizer is None or not hasattr(recognizer, "voice_evidence_status"):
            return {"status": "not_requested", "audio_speakers": []}
        try:
            result = recognizer.voice_evidence_status(window_id)
        except Exception as exc:
            return {
                "status": "failed",
                "audio_speakers": [],
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
        return result if isinstance(result, dict) else {
            "status": "failed",
            "audio_speakers": [],
        }

    async def _interpret_scene(
        self,
        *,
        window_id: str,
        captured_at_ms: int,
        duration_ms: int,
        wav_uri: str,
        wav_path: str,
        transcript: str,
        evidence: list[dict[str, Any]],
        images: list[dict[str, Any]],
        visible_people: list[dict[str, Any]],
        audio_speakers: list[dict[str, Any]],
        technical_window: dict[str, Any],
    ) -> dict[str, Any]:
        if self.scene_interpreter is None:
            return _scene_failure("scene_interpreter_not_configured")
        experience_window = dict(technical_window)
        experience_window.pop("object_perception", None)
        try:
            result = await self.scene_interpreter.interpret_window(
                window_id=window_id,
                captured_at_ms=captured_at_ms,
                duration_ms=duration_ms,
                wav_uri=wav_uri,
                wav_path=wav_path,
                transcript=transcript,
                evidence=evidence,
                images=images,
                visible_people=visible_people,
                audio_speakers=audio_speakers,
                technical_window=experience_window,
            )
        except Exception as exc:
            return _scene_failure(f"{type(exc).__name__}: {exc}")
        return result if isinstance(result, dict) else _scene_failure("non_object_result")

    async def _stabilize_context(
        self,
        *,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        window_interpretation: dict[str, Any],
    ) -> dict[str, Any]:
        stabilizer = self.event_context_stabilizer
        if stabilizer is None:
            return _stabilization_fallback(
                window_id=window_id,
                interpretation=window_interpretation,
                reason="event_context_stabilizer_not_configured",
                status="not_requested",
            )
        try:
            result = await stabilizer.stabilize_window(
                boot_session_id=boot_session_id,
                window_id=window_id,
                captured_at_ms=captured_at_ms,
                window_interpretation=window_interpretation,
            )
        except Exception as exc:
            return _stabilization_fallback(
                window_id=window_id,
                interpretation=window_interpretation,
                reason=f"{type(exc).__name__}: {exc}",
                status="failed",
            )
        if not isinstance(result, dict):
            return _stabilization_fallback(
                window_id=window_id,
                interpretation=window_interpretation,
                reason="non_object_result",
                status="failed",
            )
        return result

    async def _transcribe_audio_chunks(
        self,
        audio_chunks: list[StoredEvidence],
        sample_rate: int,
    ) -> str:
        if self.audio_transcriber is None:
            return ""
        texts: list[str] = []
        group = bytearray()
        for evidence in sorted(audio_chunks, key=lambda item: item.path.name):
            body = evidence.path.read_bytes()
            if group and len(group) + len(body) > self.transcription_chunk_bytes:
                text = await self.audio_transcriber.transcribe(bytes(group), sample_rate)
                if text.strip():
                    texts.append(text.strip())
                group.clear()
            group.extend(body)
        if group:
            text = await self.audio_transcriber.transcribe(bytes(group), sample_rate)
            if text.strip():
                texts.append(text.strip())
        return "\n".join(texts)

    @staticmethod
    def _audio_bytes(audio_chunks: list[StoredEvidence]) -> bytes:
        return b"".join(
            evidence.path.read_bytes()
            for evidence in sorted(audio_chunks, key=lambda item: item.path.name)
        )

    async def _analyze_audio_presence(
        self,
        *,
        window_id: str,
        pcm_bytes: bytes,
        sample_rate: int,
        audio_evidence_refs: list[str],
    ) -> dict[str, Any]:
        detector = self.speech_presence_detector
        if detector is None:
            error = RuntimeError("speech presence detector is not configured")
            return failed_presence_result(
                window_id=window_id,
                audio_evidence_refs=audio_evidence_refs,
                provider="unavailable",
                model="unavailable",
                method_version="presence-unavailable",
                error=error,
                latency_ms=0,
            )
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                result = await detector.analyze(
                    pcm_bytes,
                    sample_rate,
                    window_id=window_id,
                    audio_evidence_refs=audio_evidence_refs,
                )
            except Exception as exc:
                last_error = exc
                continue
            if not isinstance(result, dict):
                last_error = TypeError("speech presence detector returned a non-object")
                continue
            if attempt:
                result.setdefault("warnings", []).append("retry_succeeded")
            return result
        assert last_error is not None
        return failed_presence_result(
            window_id=window_id,
            audio_evidence_refs=audio_evidence_refs,
            provider=type(detector).__name__,
            model=str(getattr(detector, "model_id", "unknown")),
            method_version=str(getattr(detector, "method_version", "unknown")),
            error=last_error,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    async def _transcribe_presence_segments(
        self,
        pcm_bytes: bytes,
        sample_rate: int,
        segments: list[dict[str, Any]],
    ) -> str:
        if self.audio_transcriber is None:
            return ""
        bytes_per_ms = sample_rate * 2 / 1000
        groups: list[bytes] = []
        current = bytearray()
        separator = bytes(round(sample_rate * 0.2) * 2)
        for item in segments:
            start_ms = max(0, int(item.get("start_ms") or 0))
            end_ms = max(start_ms, int(item.get("end_ms") or start_ms))
            start_byte = int(start_ms * bytes_per_ms) // 2 * 2
            end_byte = int(end_ms * bytes_per_ms) // 2 * 2
            body = pcm_bytes[start_byte:end_byte]
            if not body:
                continue
            addition = body if not current else separator + body
            if current and len(current) + len(addition) > self.transcription_chunk_bytes:
                groups.append(bytes(current))
                current.clear()
                addition = body
            current.extend(addition)
        if current:
            groups.append(bytes(current))

        texts = []
        for group in groups:
            text = await self.audio_transcriber.transcribe(group, sample_rate)
            if text.strip():
                texts.append(text.strip())
        return "\n".join(texts)

    @staticmethod
    def _first_person_caption(transcript: str, image_count: int) -> str:
        if transcript.strip():
            return f"我听见：{transcript.strip()[:800]}"
        if image_count:
            return "这一小段时间里我没有听清可转写的人声；现场画面和环境音已保留。"
        return "这一小段时间里我没有听清可转写的人声；现场环境音已保留。"

    @staticmethod
    def _boot_key_from_window_id(window_id: str) -> str:
        if len(window_id) > 5 and window_id[-5] == "-" and window_id[-4:].isdigit():
            return window_id[:-5]
        return window_id

    @staticmethod
    def _event_type(
        interpretation: dict[str, Any],
        *,
        transcript: str,
        objects: list[dict[str, Any]],
    ) -> str:
        event_type = interpretation.get("event_type")
        if event_type in {"daily", "object", "person", "meeting", "unknown"}:
            return str(event_type)
        likelihood = interpretation.get("meeting_likelihood")
        if isinstance(likelihood, (int, float)) and float(likelihood) >= 0.65:
            return "meeting"
        if objects:
            return "object"
        if transcript.strip():
            return "meeting"
        return "daily"

    @staticmethod
    def _objects_with_image_uris(
        objects: list[dict[str, Any]],
        images: list[dict[str, Any]],
        *,
        object_perception: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        by_id = {
            str(image.get("id")): str(image.get("uri"))
            for image in images
            if image.get("id") and image.get("uri")
        }
        fallback_image = next(
            (
                {
                    "id": str(image.get("id") or ""),
                    "uri": str(image.get("uri") or ""),
                }
                for image in images
                if image.get("id") and image.get("uri")
            ),
            {"id": "", "uri": ""},
        )
        detector_jobs_by_evidence: dict[str, list[str]] = {}
        for frame in (object_perception or {}).get("frames") or []:
            if not isinstance(frame, dict) or not frame.get("evidence_id"):
                continue
            job_id = str(frame.get("job_id") or "").strip()
            if job_id:
                detector_jobs_by_evidence.setdefault(
                    str(frame["evidence_id"]), []
                ).append(job_id)
        normalized: list[dict[str, Any]] = []
        for item in objects:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("object_label") or "").strip()
            if not label or item.get("memory_value") == "ignore":
                continue
            evidence_id = str(item.get("evidence_id") or "").strip()
            image_uri = str(item.get("image_uri") or item.get("uri") or by_id.get(evidence_id, ""))
            if not image_uri and fallback_image["uri"]:
                evidence_id = fallback_image["id"]
                image_uri = fallback_image["uri"]
            confidence = item.get("confidence")
            if not isinstance(confidence, (int, float)):
                confidence = 0.5
            normalized.append(
                {
                    "label": label,
                    "normalized_label": item.get("normalized_label"),
                    "personal_object_id": item.get("personal_object_id"),
                    "visible_description": item.get("visible_description"),
                    "relation": item.get("relation"),
                    "confidence": max(0.0, min(1.0, float(confidence))),
                    "semantic_confidence": item.get("semantic_confidence", confidence),
                    "location_hint": item.get("location_hint") or item.get("location"),
                    "memory_value": item.get("memory_value", "memory_critical"),
                    "instance_ambiguity": bool(item.get("instance_ambiguity", False)),
                    "evidence_id": evidence_id,
                    "evidence_refs": item.get("evidence_refs") or [evidence_id],
                    "image_uri": image_uri,
                    "evidence_available": item.get("evidence_available", True),
                    "source_model": item.get("source_model"),
                    "source_prompt_version": item.get("source_prompt_version"),
                    "detector_job_ids": list(
                        dict.fromkeys(
                            [
                                *[str(value) for value in item.get("detector_job_ids") or []],
                                *detector_jobs_by_evidence.get(evidence_id, []),
                            ]
                        )
                    ),
                    "sequence": item.get("sequence"),
                }
            )
        return normalized

    def _add_object_observations(
        self,
        *,
        objects: list[dict[str, Any]],
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        source_capsule_id: str | None = None,
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for item in objects:
            label = str(item.get("label") or item.get("object_label") or "").strip()
            if not label:
                continue
            evidence_ids = [
                str(value)
                for value in (
                    item.get("evidence_ids")
                    or item.get("evidence_refs")
                    or [item.get("evidence_id") or window_id]
                )
                if value
            ]
            image_uri = str(item.get("image_uri") or item.get("uri") or "")
            observations.append(
                self.review_store.add_semantic_object_observation(
                    object_label_raw=label,
                    normalized_label=item.get("normalized_label"),
                    personal_object_id=item.get("personal_object_id"),
                    visible_description=item.get("visible_description")
                    or item.get("description"),
                    relation=item.get("relation"),
                    location_hint=item.get("location_hint") or item.get("location"),
                    memory_value=str(item.get("memory_value") or "memory_critical"),
                    semantic_confidence=float(
                        item.get("semantic_confidence")
                        if item.get("semantic_confidence") is not None
                        else item.get("confidence") or 0.5
                    ),
                    captured_at_ms=captured_at_ms,
                    boot_session_id=boot_session_id,
                    window_id=window_id,
                    evidence_ids=evidence_ids,
                    evidence_uris=[image_uri] if image_uri else [],
                    evidence_available=bool(item.get("evidence_available", True)),
                    source_capsule_id=source_capsule_id,
                    source_model=str(item.get("source_model") or "multimodal-scene"),
                    source_prompt_version=str(
                        item.get("source_prompt_version") or "scene-contract-current"
                    ),
                    detector_job_ids=[
                        str(value) for value in item.get("detector_job_ids") or [] if value
                    ],
                    instance_ambiguity=bool(item.get("instance_ambiguity", False)),
                    correction_source_id=item.get("correction_source_id"),
                    sequence=item.get("sequence"),
                )
            )
        return observations

    def _add_meeting_evidence(
        self,
        *,
        event_type: str,
        meeting: Any,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        caption: str,
        evidence: list[dict[str, Any]],
        visible_people: list[dict[str, Any]],
        audio_speakers: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if event_type != "meeting":
            return None
        meeting = meeting if isinstance(meeting, dict) else {}
        return self.review_store.add_meeting_evidence(
            {
                "boot_session_id": boot_session_id,
                "window_id": window_id,
                "captured_at_ms": captured_at_ms,
                "summary": meeting.get("summary") or caption,
                "commitments": meeting.get("commitments") or [],
                "transcript_excerpt": meeting.get("transcript_excerpt") or "",
                "visible_people": visible_people,
                "audio_speakers": audio_speakers,
                "evidence": evidence,
            }
        )

    @staticmethod
    def _caption_only_everos_text(caption: str) -> str:
        """Return only user-facing memory prose for the EverOS message.

        Window ids, evidence refs, VAD/ASR state and model audit data stay in
        the bridge manifest and must not pollute long-term memory prose.
        """

        return str(caption or "").strip()[:1200]

    @staticmethod
    def _everos_text(
        *,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        duration_ms: int,
        transcript: str,
        caption: str,
        scene: Any,
        activity: Any,
        event_type: str,
        meeting_likelihood: Any,
        objects: list[dict[str, Any]],
        meeting: Any,
        evidence: list[dict[str, Any]],
        visible_people: list[dict[str, Any]],
        audio_speakers: list[dict[str, Any]],
        clock: dict[str, Any] | None = None,
        evidence_status: dict[str, Any] | None = None,
        audio_presence: dict[str, Any] | None = None,
        asr: dict[str, Any] | None = None,
        observations: list[dict[str, Any]] | None = None,
        uncertainties: list[str] | None = None,
        input_usage: dict[str, Any] | None = None,
        stabilized_projection: dict[str, Any] | None = None,
    ) -> str:
        lines = [
            f"智能眼镜连续记忆 capsule {window_id}",
            f"boot_session_id: {boot_session_id}",
            f"captured_at_ms: {captured_at_ms}",
            f"duration_ms: {duration_ms}",
            f"事件类型：{event_type}",
            f"第一人称观察：{caption}",
            "说明：原始音频已保留，ASR 只是线索；后续可由云端多模态模型结合画面与音色重新理解。",
            "technical_window_is_event: false",
        ]
        if clock:
            lines.insert(3, f"captured_at_local: {clock.get('window_started_at_local')}")
            lines.insert(4, f"timezone_name: {clock.get('timezone_name')}")
        if scene:
            lines.insert(5, f"当前环境：{scene}")
        if activity:
            lines.insert(6 if scene else 5, f"推测我正在做：{activity}")
        observation_lines = []
        for item in observations or []:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            refs = "、".join(str(ref) for ref in item.get("evidence_refs") or [])
            suffix = f" [{refs}]" if refs else ""
            observation_lines.append(f"{item['text']}{suffix}")
        if observation_lines:
            lines.append("直接观察：" + "；".join(observation_lines[:10]))
        uncertainty_lines = [str(item).strip() for item in uncertainties or [] if str(item).strip()]
        if uncertainty_lines:
            lines.append("不确定性：" + "；".join(uncertainty_lines[:10]))
        if input_usage:
            lines.append(
                "多模态成功层级："
                f"{input_usage.get('successful_level') or 'unknown'}"
                f"（fallback={str(bool(input_usage.get('fallback_used'))).lower()}）"
            )
        if stabilized_projection:
            lines.append(
                "跨窗口稳定："
                f"{stabilized_projection.get('status') or 'unknown'}；"
                f"queue_action={stabilized_projection.get('queue_action') or 'unknown'}；"
                f"boundary_decision={stabilized_projection.get('boundary_decision') or 'unknown'}"
            )
            if stabilized_projection.get("event_queue_id"):
                lines.append(f"event_queue_id: {stabilized_projection['event_queue_id']}")
            source_ids = stabilized_projection.get("source_window_ids") or []
            if source_ids:
                lines.append("stabilized_source_window_ids: " + ", ".join(map(str, source_ids)))
            candidate_commitments = [
                item
                for item in stabilized_projection.get("candidate_commitments", [])
                if isinstance(item, dict) and item.get("text")
            ]
            if candidate_commitments:
                lines.append(
                    "候选承诺（未确认）："
                    + "；".join(
                        f"{item.get('owner') or '未知'}: {item.get('text')}"
                        for item in candidate_commitments[:10]
                    )
                )
        if isinstance(meeting_likelihood, (int, float)):
            lines.append(f"会议可能性：{float(meeting_likelihood):.2f}")
        visible = "、".join(
            dict.fromkeys(str(item.get("name") or item.get("candidate_id") or "").strip() for item in visible_people)
        ).strip("、")
        speakers = "、".join(
            dict.fromkeys(str(item.get("name") or item.get("candidate_id") or "").strip() for item in audio_speakers)
        ).strip("、")
        if visible:
            lines.append(f"我面前的人：{visible}")
        if speakers:
            lines.append(f"正在说话的人：{speakers}")
        missing_modalities = list((evidence_status or {}).get("missing_modalities") or [])
        if missing_modalities:
            lines.append("证据不足：缺少 " + "、".join(str(item) for item in missing_modalities))
        if audio_presence:
            lines.append(
                "声音存在判断："
                f"{audio_presence.get('presence_class') or 'unknown'}"
                f"（{audio_presence.get('status') or 'unknown'}）"
            )
        if asr:
            lines.append(f"ASR 状态：{asr.get('status') or 'unknown'}")
        object_lines = []
        for item in objects:
            if item.get("memory_value", "memory_critical") != "memory_critical":
                continue
            label = str(item.get("label") or item.get("object_label") or "").strip()
            if not label:
                continue
            where = item.get("location_hint") or item.get("location") or "未知位置"
            confidence = item.get("confidence")
            if isinstance(confidence, (int, float)):
                object_lines.append(f"{label}@{where}({float(confidence):.2f})")
            else:
                object_lines.append(f"{label}@{where}")
        if object_lines:
            lines.append("物品观察：" + "；".join(object_lines[:10]))
        if event_type == "meeting" and isinstance(meeting, dict):
            summary = str(meeting.get("summary") or "").strip()
            if summary:
                lines.append(f"会议摘要：{summary}")
            commitments = [
                item
                for item in meeting.get("commitments", [])
                if isinstance(item, dict) and item.get("text")
            ]
            if commitments:
                lines.append(
                    "会议承诺："
                    + "；".join(
                        f"{item.get('owner') or '未知'}: {item.get('text')}"
                        for item in commitments[:10]
                    )
                )
        refs = [str(item.get("id") or item.get("uri")) for item in evidence if item.get("id") or item.get("uri")]
        if refs:
            lines.append("bridge_evidence_refs: " + ", ".join(refs[:20]))
        return "\n".join(lines)

    def _should_flush(self, boot_session: dict[str, Any], captured_at_ms: int) -> bool:
        last_flush = int(boot_session.get("last_flush_at_ms") or boot_session.get("started_at_ms") or captured_at_ms)
        return captured_at_ms - last_flush >= self.flush_interval_ms

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest["updated_at_ms"] = int(time.time() * 1000)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _load_manifest(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    async def _collect_object_perception(
        self,
        images: list[dict[str, Any]],
    ) -> dict[str, Any]:
        evidence_ids = [str(item.get("id")) for item in images if item.get("id")]
        if not evidence_ids:
            return {"status": "not_requested", "reason": "no_images", "frames": []}
        if self.object_perception is None:
            return {
                "status": "not_requested",
                "reason": "object_perception_disabled",
                "frames": [
                    {
                        "evidence_id": evidence_id,
                        "status": "unavailable_failed",
                        "detections": [],
                    }
                    for evidence_id in evidence_ids
                ],
            }
        try:
            return await self.object_perception.hints_for_evidence(evidence_ids)
        except Exception as exc:
            return {
                "status": "unavailable_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "frames": [
                    {
                        "evidence_id": evidence_id,
                        "status": "unavailable_failed",
                        "detections": [],
                    }
                    for evidence_id in evidence_ids
                ],
            }

    async def _process_object_cards(
        self,
        *,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        source_capsule_id: str,
        caption: str,
        images: list[dict[str, Any]],
        object_perception: dict[str, Any],
    ) -> dict[str, Any]:
        if self.object_card_interpreter is None:
            return {
                "contract_version": "object-card-v1",
                "status": "not_requested",
                "candidate_count": 0,
                "observations": [],
                "schema_errors": ["object_card_interpreter_not_configured"],
            }
        try:
            result = await self.object_card_interpreter.process_window(
                boot_session_id=boot_session_id,
                window_id=window_id,
                captured_at_ms=captured_at_ms,
                source_capsule_id=source_capsule_id,
                caption=caption,
                images=images,
                object_perception=object_perception,
            )
        except Exception as exc:
            return {
                "contract_version": "object-card-v1",
                "status": "failed",
                "candidate_count": 0,
                "observations": [],
                "schema_errors": [f"{type(exc).__name__}: {exc}"],
            }
        return result if isinstance(result, dict) else {
            "contract_version": "object-card-v1",
            "status": "failed",
            "candidate_count": 0,
            "observations": [],
            "schema_errors": ["non_object_result"],
        }

    async def _extract_commitments(
        self,
        *,
        window_id: str,
        capsule_id: str,
        captured_at_ms: int,
        transcript: str,
        audio_speakers: list[dict[str, Any]],
        evidence_refs: list[str],
    ) -> dict[str, Any]:
        if self.commitment_extractor is None:
            return {
                "contract_version": "commitment-extraction-v1",
                "status": "not_requested",
                "candidate_count": 0,
                "candidates": [],
                "schema_errors": ["commitment_extractor_not_configured"],
            }
        try:
            result = await self.commitment_extractor.process_window(
                window_id=window_id,
                capsule_id=capsule_id,
                captured_at_ms=captured_at_ms,
                transcript=transcript,
                audio_speakers=audio_speakers,
                evidence_refs=evidence_refs,
            )
        except Exception as exc:
            return {
                "contract_version": "commitment-extraction-v1",
                "status": "failed",
                "candidate_count": 0,
                "candidates": [],
                "schema_errors": [f"{type(exc).__name__}: {exc}"],
            }
        return result if isinstance(result, dict) else {
            "contract_version": "commitment-extraction-v1",
            "status": "failed",
            "candidate_count": 0,
            "candidates": [],
            "schema_errors": ["non_object_result"],
        }

    @staticmethod
    def _capsule_id(boot_session_id: str, window_id: str) -> str:
        import hashlib

        digest = hashlib.sha256(f"{boot_session_id}\n{window_id}".encode("utf-8")).hexdigest()
        return f"cap-{digest[:12]}"

    @staticmethod
    def _presence_history(
        manifest_path: Path,
        current: dict[str, Any],
    ) -> list[dict[str, Any]]:
        previous: list[dict[str, Any]] = []
        if manifest_path.is_file():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                processing = payload.get("processing") if isinstance(payload, dict) else {}
                runs = processing.get("audio_presence_runs") if isinstance(processing, dict) else []
                if isinstance(runs, list):
                    previous = [item for item in runs if isinstance(item, dict)]
                elif isinstance(processing, dict) and isinstance(
                    processing.get("audio_presence"), dict
                ):
                    previous = [processing["audio_presence"]]
            except (OSError, ValueError):
                previous = []
        run_id = current.get("presence_run_id")
        if run_id and any(item.get("presence_run_id") == run_id for item in previous):
            return previous
        return [*previous, current]

    @staticmethod
    def _asr_history(
        manifest_path: Path,
        current: dict[str, Any],
    ) -> list[dict[str, Any]]:
        previous: list[dict[str, Any]] = []
        if manifest_path.is_file():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                processing = payload.get("processing") if isinstance(payload, dict) else {}
                runs = processing.get("asr_runs") if isinstance(processing, dict) else []
                if isinstance(runs, list):
                    previous = [item for item in runs if isinstance(item, dict)]
                elif isinstance(processing, dict) and isinstance(processing.get("asr"), dict):
                    previous = [processing["asr"]]
            except (OSError, ValueError):
                previous = []
        run_id = current.get("asr_run_id")
        if run_id and any(item.get("asr_run_id") == run_id for item in previous):
            return previous
        return [*previous, current]


def _claim_value(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        text = str(value.get("value") or value.get("text") or "").strip()
        return text or None
    return None


def _stabilization_fallback(
    *,
    window_id: str,
    interpretation: dict[str, Any],
    reason: str,
    status: str,
) -> dict[str, Any]:
    return {
        "contract_version": "semantic-session-boundary-v1",
        "status": status,
        "contract_valid": False,
        "schema_errors": [reason],
        "stabilizer_mode": "pending_repair",
        "queue_action": "pending_repair",
        "source_window_ids": [window_id],
        "corrected_caption": str(interpretation.get("first_person_caption") or ""),
        "boundary_reason": reason,
        "sealed_event_summary": "",
        "latency_ms": 0,
        "usage": {},
    }


def _scene_failure(reason: str) -> dict[str, Any]:
    return {
        "contract_version": "first-person-caption-v1",
        "status": "failed",
        "contract_valid": False,
        "schema_errors": ["interpretation_failed"],
        "evidence_refs": [],
        "input_usage": {
            "successful_level": "failed",
            "attempted_levels": [],
            "attached_image_count": 0,
            "attached_audio": False,
            "asr_present": False,
            "fallback_used": False,
            "failure_reason": reason,
        },
    }
