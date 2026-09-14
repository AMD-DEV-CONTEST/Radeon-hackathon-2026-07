from __future__ import annotations

from typing import Any, Callable

from .alignment import align_asr_segments
from .directory import VoiceCandidateDirectory
from .store import VoiceJobStore


class VoiceCandidatePostprocessor:
    """Turn alignment and anonymous candidate projection after worker completion."""

    def __init__(
        self,
        *,
        job_store: VoiceJobStore,
        directory: VoiceCandidateDirectory,
        projection_callback: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.job_store = job_store
        self.directory = directory
        self.projection_callback = projection_callback

    def process_job(
        self,
        job_id: str,
        *,
        asr_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        job = self.job_store.get_job(job_id, internal=True)
        if job is None:
            raise KeyError(job_id)
        if job.get("status") not in {"ready", "ready_no_eligible_turn", "ready_no_speech"}:
            return {
                "status": "voice_job_not_ready",
                "job_id": job_id,
                "audio_speakers": [],
                "asr_alignment": {"status": "not_requested", "assignments": []},
            }
        turns = self.job_store.turns_for_job(job_id)
        assignments: dict[str, dict[str, Any]] = {}
        for speaker_local_id in sorted(
            {str(item.get("speaker_local_id") or "") for item in turns if item.get("speaker_local_id")}
        ):
            speaker_turns = [
                item for item in turns if item.get("speaker_local_id") == speaker_local_id
            ]
            embeddings = []
            for turn in speaker_turns:
                if not (turn.get("quality") or {}).get("eligible_for_match"):
                    continue
                embedding = self.job_store.protected_embedding(str(turn["turn_id"]))
                if embedding:
                    embeddings.append(
                        (embedding, int(turn["end_ms"]) - int(turn["start_ms"]))
                    )
            assignments[speaker_local_id] = self.directory.ingest_local_speaker(
                job=job,
                speaker_local_id=speaker_local_id,
                turns=speaker_turns,
                embeddings=embeddings,
            )
        candidate_turns = []
        for turn in turns:
            assignment = assignments.get(str(turn.get("speaker_local_id") or ""), {})
            candidate_turns.append(
                {
                    **turn,
                    "voice_candidate_id": assignment.get("candidate_id"),
                    "confirmed_person_id": assignment.get("confirmed_person_id"),
                }
            )
        alignment = align_asr_segments(turns=candidate_turns, asr_result=asr_result)
        audio_speakers = self._audio_speakers(
            job=job,
            turns=alignment["turns"],
            assignments=assignments,
            transcript_by_speaker=alignment["transcript_by_speaker"],
            asr_assignments=alignment["assignments"],
        )
        self.job_store.save_postprocessing(
            job_id,
            turns=alignment["turns"],
            audio_speakers=audio_speakers,
            asr_alignment={
                key: value
                for key, value in alignment.items()
                if key not in {"turns", "transcript_by_speaker"}
            },
        )
        result = {
            "status": "completed",
            "job_id": job_id,
            "audio_speakers": audio_speakers,
            "asr_alignment": {
                key: value
                for key, value in alignment.items()
                if key not in {"turns", "transcript_by_speaker"}
            },
        }
        if self.projection_callback is not None:
            self.projection_callback(str(job.get("window_id") or ""), result)
        return result

    @staticmethod
    def _audio_speakers(
        *,
        job: dict[str, Any],
        turns: list[dict[str, Any]],
        assignments: dict[str, dict[str, Any]],
        transcript_by_speaker: dict[str, str],
        asr_assignments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates = {
            str(item.get("speaker_local_id") or "")
            for item in turns
            if item.get("speaker_local_id")
        }
        output = []
        for speaker in sorted(candidates):
            speaker_turns = [item for item in turns if item.get("speaker_local_id") == speaker]
            assignment = assignments.get(speaker) or {}
            candidate_id = assignment.get("candidate_id")
            confirmed_person_id = assignment.get("confirmed_person_id")
            ambiguous_refs = [
                item["asr_segment_id"]
                for item in asr_assignments
                if item.get("status") == "ambiguous_speaker"
                and any(candidate.get("speaker_local_id") == speaker for candidate in item.get("candidates") or [])
            ]
            output.append(
                {
                    "candidate_id": candidate_id,
                    "name": (
                        str(assignment.get("display_name") or candidate_id)
                        if candidate_id
                        else f"未分配说话人 {speaker}"
                    ),
                    "candidate_status": (
                        "confirmed"
                        if confirmed_person_id
                        else "candidate"
                        if candidate_id
                        else "unassigned"
                    ),
                    "confirmed_person_id": confirmed_person_id,
                    "speaker_local_id": speaker,
                    "start_ms": min(int(item["start_ms"]) for item in speaker_turns),
                    "end_ms": max(int(item["end_ms"]) for item in speaker_turns),
                    "transcript": transcript_by_speaker.get(speaker, ""),
                    "confidence": assignment.get("match_confidence"),
                    "overlap": any(bool(item.get("overlap")) for item in speaker_turns),
                    "ambiguous_asr_segment_refs": ambiguous_refs,
                    "asr_segment_refs": list(
                        dict.fromkeys(
                            ref
                            for item in speaker_turns
                            for ref in item.get("asr_segment_refs") or []
                        )
                    ),
                    "turn_ids": [str(item["turn_id"]) for item in speaker_turns],
                    "evidence_id": job.get("audio_evidence_id"),
                    "window_id": job.get("window_id"),
                    "source": "voice_worker",
                    "gallery_suggestion": assignment.get("gallery_suggestion"),
                    "identity_preassigned": True,
                }
            )
        return output
