from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
import wave

from .contracts import StaleVoiceModelRevisionError, VoiceAudioDecodeError


class ProductionVoiceEngine:
    """Local CUDA diarization/embedding engine bound to the MVP-12A lock."""

    def __init__(
        self,
        *,
        config_path: str | Path,
        allowed_media_root: str | Path,
        runtime_root: str | Path = "/opt/beaver/models/speaker",
        backend_factory: Callable[[dict[str, Any], Path], Any] | None = None,
    ) -> None:
        self.config_path = Path(config_path).expanduser().resolve()
        self.allowed_media_root = Path(allowed_media_root).expanduser().resolve()
        self.runtime_root = Path(runtime_root).expanduser().resolve()
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        if self.config.get("status") != "production_locked":
            raise ValueError("voice worker requires a production_locked config")
        self.config_version = str(self.config["config_version"])
        self.model_revision = voice_model_revision_from_config(self.config)
        self._backend_factory = backend_factory
        self._backend: Any = None
        self._loaded_at_ms: int | None = None
        self._lock = threading.RLock()

    def process(
        self,
        *,
        audio_path: str,
        media_type: str,
        speech_present: bool | None,
        expected_model_revision: str,
        expected_config_version: str,
    ) -> dict[str, Any]:
        with self._lock:
            return self._process_serialized(
                audio_path=audio_path,
                media_type=media_type,
                speech_present=speech_present,
                expected_model_revision=expected_model_revision,
                expected_config_version=expected_config_version,
            )

    def _process_serialized(
        self,
        *,
        audio_path: str,
        media_type: str,
        speech_present: bool | None,
        expected_model_revision: str,
        expected_config_version: str,
    ) -> dict[str, Any]:
        if expected_model_revision != self.model_revision:
            raise StaleVoiceModelRevisionError("voice model revision mismatch")
        if expected_config_version != self.config_version:
            raise StaleVoiceModelRevisionError("voice config version mismatch")
        if media_type not in {"audio/wav", "audio/x-wav", "audio/wave"}:
            raise VoiceAudioDecodeError(f"unsupported voice media type: {media_type}")
        path = Path(audio_path).expanduser().resolve()
        if not path.is_relative_to(self.allowed_media_root):
            raise PermissionError("voice audio path is outside the controlled media root")
        if not path.is_file():
            raise FileNotFoundError(path)
        sample_rate, duration_ms = _probe_wave(path)
        if sample_rate != int(self.config["sample_rate"]):
            raise VoiceAudioDecodeError(
                f"voice sample rate {sample_rate} != required {self.config['sample_rate']}"
            )
        if speech_present is False:
            return self._result(
                status="ready_no_speech",
                turns=[],
                duration_ms=duration_ms,
                sample_rate=sample_rate,
                latency_ms=0.0,
                speaker_count=0,
                eligible_speaker_count=0,
            )

        backend = self._load_backend()
        started = time.perf_counter()
        raw_turns = [dict(item) for item in backend.diarize(str(path))]
        turns = _mark_overlap(raw_turns)
        activity: dict[str, int] = {}
        for turn in turns:
            speaker = str(turn["speaker_local_id"])
            activity[speaker] = activity.get(speaker, 0) + int(turn["end_ms"]) - int(
                turn["start_ms"]
            )
        minimum_turn_ms = int(self.config["minimum_turn_ms"])
        minimum_activity_ms = int(
            self.config["speaker_count_projection"]["minimum_speaker_activity_ms"]
        )
        projected_speakers = {
            speaker for speaker, value in activity.items() if value >= minimum_activity_ms
        }
        eligible_speakers: set[str] = set()
        for turn in turns:
            start_ms = int(turn["start_ms"])
            end_ms = int(turn["end_ms"])
            speaker = str(turn["speaker_local_id"])
            reasons: list[str] = []
            if end_ms - start_ms < minimum_turn_ms:
                reasons.append("turn_too_short")
            if speaker not in projected_speakers:
                reasons.append("speaker_activity_too_short")
            if turn.get("overlap"):
                reasons.append("overlap_uncertain")
            embedding = None
            if not reasons:
                embedding = backend.embed(str(path), start_ms=start_ms, end_ms=end_ms)
                eligible_speakers.add(speaker)
            turn["quality"] = {
                "eligible_for_match": not reasons,
                "reason_codes": reasons,
                "speaker_activity_ms": activity[speaker],
            }
            turn["embedding"] = embedding
            turn.setdefault("confidence", None)
        latency_ms = (time.perf_counter() - started) * 1000.0
        status = "ready" if eligible_speakers else "ready_no_eligible_turn"
        return self._result(
            status=status,
            turns=turns,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            latency_ms=latency_ms,
            speaker_count=len(projected_speakers),
            eligible_speaker_count=len(eligible_speakers),
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "loaded": self._backend is not None,
            "model_revision": self.model_revision,
            "config_version": self.config_version,
            "loaded_at_ms": self._loaded_at_ms,
            "device": "cuda:0",
        }

    def _load_backend(self) -> Any:
        if self._backend is not None:
            return self._backend
        backend = (
            self._backend_factory(self.config, self.runtime_root)
            if self._backend_factory is not None
            else _SpeakerRuntimeBackend(self.config, self.runtime_root)
        )
        self._backend = backend
        self._loaded_at_ms = int(time.time() * 1000)
        return backend

    def _result(
        self,
        *,
        status: str,
        turns: list[dict[str, Any]],
        duration_ms: int,
        sample_rate: int,
        latency_ms: float,
        speaker_count: int,
        eligible_speaker_count: int,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "model_id": str(self.config["diarization_model"]),
            "model_revision": self.model_revision,
            "config_version": self.config_version,
            "duration_ms": int(duration_ms),
            "sample_rate": int(sample_rate),
            "latency_ms": round(float(latency_ms), 3),
            "speaker_count": int(speaker_count),
            "eligible_speaker_count": int(eligible_speaker_count),
            "turns": turns,
            "device": "cuda:0",
        }


class _SpeakerRuntimeBackend:
    def __init__(self, config: dict[str, Any], runtime_root: Path) -> None:
        import torch
        import torchaudio
        import wespeaker
        from nemo.collections.asr.models import SortformerEncLabelModel

        self.torch = torch
        self.torchaudio = torchaudio
        artifacts = dict(config.get("runtime_artifacts") or {})
        sortformer_path = Path(
            os.getenv(
                "VOICE_SORTFORMER_MODEL_PATH",
                str(runtime_root / str(artifacts["sortformer_model_relative_path"])),
            )
        ).expanduser().resolve()
        wespeaker_model = Path(
            os.getenv(
                "VOICE_WESPEAKER_MODEL_PATH",
                str(runtime_root / str(artifacts["wespeaker_model_relative_path"])),
            )
        ).expanduser().resolve()
        wespeaker_config = Path(
            os.getenv(
                "VOICE_WESPEAKER_CONFIG_PATH",
                str(runtime_root / str(artifacts["wespeaker_config_relative_path"])),
            )
        ).expanduser().resolve()
        _verify_sha256(sortformer_path, str(config["diarization_model_artifact_sha256"]))
        _verify_sha256(wespeaker_model, str(config["embedding_model_artifact_sha256"]))
        _verify_sha256(wespeaker_config, str(artifacts["wespeaker_config_sha256"]))
        self.postprocessing_yaml = Path(
            os.getenv(
                "VOICE_POSTPROCESSING_YAML",
                str(
                    Path(__file__).resolve().parents[3]
                    / str(artifacts["postprocessing_relative_path"])
                ),
            )
        ).resolve()
        _verify_sha256(
            self.postprocessing_yaml, str(artifacts["postprocessing_sha256"])
        )
        self.sortformer = SortformerEncLabelModel.restore_from(str(sortformer_path))
        self.sortformer.eval().to("cuda:0")
        self.embedder = wespeaker.load_model("chinese")
        self.embedder.set_device("cuda:0")

    def diarize(self, audio_path: str) -> list[dict[str, Any]]:
        result = self.sortformer.diarize(
            audio=[audio_path],
            batch_size=1,
            postprocessing_yaml=str(self.postprocessing_yaml),
        )
        segments = result[0] if len(result) == 1 else result
        output = []
        for item in segments:
            values = item.split() if isinstance(item, str) else list(item)
            if len(values) == 4:
                _, begin, end, label = values
            elif len(values) == 3:
                begin, end, label = values
            else:
                raise RuntimeError(f"unexpected Sortformer row: {item!r}")
            output.append(
                {
                    "start_ms": round(float(begin) * 1000),
                    "end_ms": round(float(end) * 1000),
                    "speaker_local_id": f"speaker_local_{str(label).split('_')[-1]}",
                }
            )
        return output

    def embed(self, audio_path: str, *, start_ms: int, end_ms: int) -> list[float]:
        pcm, sample_rate = self.torchaudio.load(
            audio_path,
            frame_offset=round(start_ms * 16),
            num_frames=max(1, round((end_ms - start_ms) * 16)),
            normalize=self.embedder.wavform_norm,
        )
        if pcm.shape[0] > 1:
            pcm = pcm.mean(dim=0, keepdim=True)
        if sample_rate != self.embedder.resample_rate:
            pcm = self.torchaudio.functional.resample(
                pcm, sample_rate, self.embedder.resample_rate
            )
        feats = self.embedder.compute_features(
            pcm.float(), sample_rate=self.embedder.resample_rate, cmn=True
        ).to(self.embedder.device)
        with self.torch.no_grad():
            value = self.embedder.model(feats)
            value = value[-1] if isinstance(value, tuple) else value
        return value[0].detach().cpu().float().reshape(-1).tolist()


def voice_model_revision_from_config(config_or_path: dict[str, Any] | str | Path) -> str:
    config = (
        config_or_path
        if isinstance(config_or_path, dict)
        else json.loads(Path(config_or_path).read_text(encoding="utf-8"))
    )
    payload = "\n".join(
        (
            str(config["diarization_model"]),
            str(config["diarization_model_revision"]),
            str(config["diarization_model_artifact_sha256"]),
            str(config["embedding_model"]),
            str(config["embedding_source_revision"]),
            str(config["embedding_model_artifact_sha256"]),
            str(config["candidate_threshold"]),
            str(config["minimum_turn_ms"]),
            str(config["speaker_count_projection"]["minimum_speaker_activity_ms"]),
            str(config["overlap_policy"]),
            str(config.get("engine_contract_version") or "overlap-turn-v1"),
            str((config.get("runtime_artifacts") or {})["wespeaker_config_sha256"]),
            str((config.get("runtime_artifacts") or {})["postprocessing_sha256"]),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _probe_wave(path: Path) -> tuple[int, int]:
    try:
        with wave.open(str(path), "rb") as handle:
            sample_rate = int(handle.getframerate())
            frames = int(handle.getnframes())
            if handle.getnchannels() <= 0 or handle.getsampwidth() != 2 or frames <= 0:
                raise VoiceAudioDecodeError("voice WAV must be non-empty PCM16")
    except (wave.Error, EOFError, OSError) as exc:
        raise VoiceAudioDecodeError(f"failed to decode voice WAV: {exc}") from exc
    return sample_rate, round(frames / sample_rate * 1000)


def _mark_overlap(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split turns at cross-speaker boundaries so overlap is local, not turn-wide."""

    validated = []
    for turn in turns:
        start_ms, end_ms = int(turn["start_ms"]), int(turn["end_ms"])
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("worker emitted invalid voice turn")
        speaker = str(turn.get("speaker_local_id") or "").strip()
        if not speaker:
            raise ValueError("worker emitted turn without local speaker")
        validated.append(
            {
                **turn,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "speaker_local_id": speaker,
            }
        )

    output = []
    for turn in validated:
        start_ms, end_ms = int(turn["start_ms"]), int(turn["end_ms"])
        speaker = str(turn["speaker_local_id"])
        boundaries = {start_ms, end_ms}
        for other in validated:
            if speaker == str(other["speaker_local_id"]):
                continue
            overlap_start = max(start_ms, int(other["start_ms"]))
            overlap_end = min(end_ms, int(other["end_ms"]))
            if overlap_start < overlap_end:
                boundaries.update((overlap_start, overlap_end))
        ordered = sorted(boundaries)
        for segment_start, segment_end in zip(ordered, ordered[1:]):
            if segment_end <= segment_start:
                continue
            midpoint = (segment_start + segment_end) / 2
            overlap = any(
                speaker != str(other["speaker_local_id"])
                and int(other["start_ms"]) <= midpoint < int(other["end_ms"])
                for other in validated
            )
            output.append(
                {
                    **turn,
                    "start_ms": segment_start,
                    "end_ms": segment_end,
                    "overlap": overlap,
                }
            )
    return sorted(
        output,
        key=lambda item: (
            int(item["start_ms"]),
            int(item["end_ms"]),
            str(item["speaker_local_id"]),
        ),
    )


def _verify_sha256(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError(f"voice model hash mismatch: {path.name}")
