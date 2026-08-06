from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
from pathlib import Path
import threading
import time
from typing import Any
import uuid


PRESENCE_CONTRACT_VERSION = 1
PRESENCE_CLASSES = {"silence", "environment_sound", "speech", "mixed", "unknown"}


@dataclass(frozen=True)
class PresenceSegment:
    start_ms: int
    end_ms: int
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"start_ms": self.start_ms, "end_ms": self.end_ms}
        if self.confidence is not None:
            data["confidence"] = round(float(self.confidence), 6)
        return data


@dataclass(frozen=True)
class ClassifierWindow:
    start_ms: int
    end_ms: int
    speech_probability: float
    music_probability: float


@dataclass(frozen=True)
class PresenceSignals:
    duration_ms: int
    rms_dbfs: float
    fsmn_segments: tuple[tuple[int, int], ...] = ()
    silero_segments: tuple[tuple[int, int], ...] = ()
    ten_segments: tuple[tuple[int, int], ...] = ()
    classifier_windows: tuple[ClassifierWindow, ...] = ()


@dataclass(frozen=True)
class PresenceDecisionConfig:
    silence_dbfs: float = -55.0
    speech_probability_threshold: float = 0.05
    short_speech_recovery_ms: int = 500
    segment_padding_ms: int = 200
    mixed_coverage_threshold: float = 0.95
    music_probability_threshold: float = 0.10


def decide_presence(
    signals: PresenceSignals,
    *,
    config: PresenceDecisionConfig,
) -> dict[str, Any]:
    """Turn independent VAD and acoustic-classifier signals into one contract.

    The decision is intentionally independent from ASR text. FSMN supplies
    candidate endpoints, Silero or TEN-VAD independently confirms speech, and
    the AudioSet classifier rejects music/noise. FSMN may recover a very short
    utterance that both confirmers miss, but only when the acoustic classifier
    also identifies spoken speech.
    """

    if signals.duration_ms <= 0:
        raise ValueError("presence input must contain audio")
    if signals.rms_dbfs <= config.silence_dbfs:
        return _completed_result(
            presence_class="silence",
            duration_ms=signals.duration_ms,
            rms_dbfs=signals.rms_dbfs,
            segments=[],
            speech_probability=0.0,
            music_probability=0.0,
            non_speech_activity=False,
            warnings=[],
        )

    accepted: list[PresenceSegment] = []
    rejected_music = 0
    rejected_unconfirmed = 0
    for start_ms, end_ms in signals.fsmn_segments:
        start_ms = max(0, int(start_ms))
        end_ms = min(signals.duration_ms, int(end_ms))
        if end_ms <= start_ms:
            continue
        classifier = _best_classifier_window(
            signals.classifier_windows,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        if classifier is None:
            rejected_unconfirmed += 1
            continue
        speech_probability = classifier.speech_probability
        music_probability = classifier.music_probability
        if (
            speech_probability < config.speech_probability_threshold
            or speech_probability <= music_probability
        ):
            rejected_music += 1
            continue
        silero_confirmed = any(
            _overlap_ms(start_ms, end_ms, silero_start, silero_end) > 0
            for silero_start, silero_end in signals.silero_segments
        )
        ten_confirmed = any(
            _overlap_ms(start_ms, end_ms, ten_start, ten_end) > 0
            for ten_start, ten_end in signals.ten_segments
        )
        if (
            not silero_confirmed
            and not ten_confirmed
            and end_ms - start_ms > config.short_speech_recovery_ms
        ):
            rejected_unconfirmed += 1
            continue
        accepted.append(
            PresenceSegment(
                start_ms=max(0, start_ms - config.segment_padding_ms),
                end_ms=min(signals.duration_ms, end_ms + config.segment_padding_ms),
                confidence=speech_probability,
            )
        )

    merged = _merge_segments(accepted)
    coverage_ms = sum(item.end_ms - item.start_ms for item in merged)
    coverage = coverage_ms / signals.duration_ms
    speech_probability = max(
        (item.speech_probability for item in signals.classifier_windows),
        default=0.0,
    )
    music_probability = max(
        (item.music_probability for item in signals.classifier_windows),
        default=0.0,
    )
    warnings = []
    if rejected_music:
        warnings.append(f"rejected_music_or_non_speech_segments:{rejected_music}")
    if rejected_unconfirmed:
        warnings.append(f"rejected_unconfirmed_segments:{rejected_unconfirmed}")

    if not merged:
        return _completed_result(
            presence_class="environment_sound",
            duration_ms=signals.duration_ms,
            rms_dbfs=signals.rms_dbfs,
            segments=[],
            speech_probability=speech_probability,
            music_probability=music_probability,
            non_speech_activity=True,
            warnings=warnings,
        )

    non_speech_activity = (
        coverage < config.mixed_coverage_threshold
        or music_probability >= config.music_probability_threshold
    )
    return _completed_result(
        presence_class="mixed" if non_speech_activity else "speech",
        duration_ms=signals.duration_ms,
        rms_dbfs=signals.rms_dbfs,
        segments=merged,
        speech_probability=speech_probability,
        music_probability=music_probability,
        non_speech_activity=non_speech_activity,
        warnings=warnings,
    )


class CompositeSpeechPresenceDetector:
    """Server-side spoken-speech gate with lazy, pinned local models."""

    method_version = "presence-m1-v1"

    def __init__(
        self,
        *,
        fsmn_model_path: str | Path,
        audioset_model_path: str | Path,
        fsmn_revision: str,
        audioset_revision: str,
        silero_version: str,
        ten_vad_version: str | None = None,
        ten_vad_enabled: bool = False,
        ten_vad_threshold: float = 0.90,
        ten_vad_min_frames: int = 3,
        device: str = "cuda:0",
        classifier_window_ms: int = 5_000,
        decision_config: PresenceDecisionConfig | None = None,
    ) -> None:
        self.fsmn_model_path = Path(fsmn_model_path).resolve()
        self.audioset_model_path = Path(audioset_model_path).resolve()
        self.fsmn_revision = fsmn_revision
        self.audioset_revision = audioset_revision
        self.silero_version = silero_version
        self.ten_vad_version = ten_vad_version
        self.ten_vad_enabled = ten_vad_enabled
        self.ten_vad_threshold = ten_vad_threshold
        self.ten_vad_min_frames = ten_vad_min_frames
        self.device = device
        self.classifier_window_ms = classifier_window_ms
        self.decision_config = decision_config or PresenceDecisionConfig()
        self._models: tuple[Any, Any, Any, Any, Any, str, Any] | None = None
        self._load_lock = threading.Lock()

    @property
    def model_id(self) -> str:
        model = (
            f"fsmn-vad@{self.fsmn_revision}+"
            f"silero-vad@{self.silero_version}+"
            f"ast-audioset@{self.audioset_revision}"
        )
        if self.ten_vad_enabled:
            model += f"+ten-vad@{self.ten_vad_version or 'unknown'}"
        return model

    async def warmup(self) -> None:
        await asyncio.to_thread(self._load_models)

    async def analyze(
        self,
        pcm_bytes: bytes,
        sample_rate: int,
        *,
        window_id: str,
        audio_evidence_refs: list[str],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        result = await asyncio.to_thread(self._analyze_sync, pcm_bytes, sample_rate)
        result.update(
            {
                "presence_run_id": f"presence-{uuid.uuid4().hex[:16]}",
                "window_id": window_id,
                "audio_evidence_refs": list(audio_evidence_refs),
                "provider": "local-composite-speech-presence",
                "model": self.model_id,
                "method_version": self.method_version,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        return result

    def _analyze_sync(self, pcm_bytes: bytes, sample_rate: int) -> dict[str, Any]:
        if sample_rate != 16_000:
            raise ValueError(f"speech presence expects 16 kHz PCM, got {sample_rate}")
        if not pcm_bytes:
            raise ValueError("speech presence input is empty")
        import numpy as np

        audio = np.frombuffer(pcm_bytes, dtype="<i2").astype("float32") / 32768.0
        duration_ms = round(len(audio) * 1000 / sample_rate)
        rms_dbfs = _rms_dbfs(audio)
        if rms_dbfs <= self.decision_config.silence_dbfs:
            return decide_presence(
                PresenceSignals(duration_ms=duration_ms, rms_dbfs=rms_dbfs),
                config=self.decision_config,
            )

        fsmn, silero, feature_extractor, classifier, torch, device, ten_vad_class = self._load_models()
        fsmn_output = fsmn.generate(input=audio, disable_pbar=True)
        fsmn_segments = _fsmn_segments(fsmn_output)
        silero.reset_states()
        from silero_vad import get_speech_timestamps

        # Silero requires a minimum analysis window. Very short or truncated
        # packets are padded for analysis, while returned endpoints are still
        # clamped to the original evidence duration.
        silero_audio = audio
        if len(silero_audio) < 512:
            silero_audio = np.pad(silero_audio, (0, 512 - len(silero_audio)))
        silero_output = get_speech_timestamps(
            silero_audio,
            silero,
            sampling_rate=sample_rate,
            threshold=0.5,
            min_speech_duration_ms=250,
            min_silence_duration_ms=300,
        )
        silero_segments = tuple(
            (
                round(int(item["start"]) * 1000 / sample_rate),
                min(duration_ms, round(int(item["end"]) * 1000 / sample_rate)),
            )
            for item in silero_output
        )
        ten_segments = (
            _ten_vad_segments(
                audio,
                ten_vad_class=ten_vad_class,
                sample_rate=sample_rate,
                threshold=self.ten_vad_threshold,
                min_frames=self.ten_vad_min_frames,
            )
            if ten_vad_class is not None
            else ()
        )
        classifier_windows = self._classify_windows(
            audio,
            sample_rate=sample_rate,
            feature_extractor=feature_extractor,
            classifier=classifier,
            torch=torch,
            device=device,
        )
        return decide_presence(
            PresenceSignals(
                duration_ms=duration_ms,
                rms_dbfs=rms_dbfs,
                fsmn_segments=fsmn_segments,
                silero_segments=silero_segments,
                ten_segments=ten_segments,
                classifier_windows=classifier_windows,
            ),
            config=self.decision_config,
        )

    def _classify_windows(
        self,
        audio: Any,
        *,
        sample_rate: int,
        feature_extractor: Any,
        classifier: Any,
        torch: Any,
        device: str,
    ) -> tuple[ClassifierWindow, ...]:
        window_samples = round(self.classifier_window_ms * sample_rate / 1000)
        chunks = []
        for offset in range(0, len(audio), window_samples):
            chunk = audio[offset : offset + window_samples]
            # Kaldi fbank uses a 25 ms / 400 sample analysis window.
            if len(chunk) < 400:
                import numpy as np

                chunk = np.pad(chunk, (0, 400 - len(chunk)))
            chunks.append(chunk)
        inputs = feature_extractor(
            chunks,
            sampling_rate=sample_rate,
            return_tensors="pt",
            padding=True,
        )
        with torch.inference_mode():
            probabilities = classifier(
                **{key: value.to(device) for key, value in inputs.items()}
            ).logits.sigmoid().cpu()
        spoken_indices = range(0, 8)
        music_indices = [*range(27, 36), *range(137, 284)]
        output = []
        for index, values in enumerate(probabilities):
            start_ms = index * self.classifier_window_ms
            end_ms = min(round(len(audio) * 1000 / sample_rate), start_ms + self.classifier_window_ms)
            output.append(
                ClassifierWindow(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    speech_probability=max(float(values[item]) for item in spoken_indices),
                    music_probability=max(float(values[item]) for item in music_indices),
                )
            )
        return tuple(output)

    def _load_models(self) -> tuple[Any, Any, Any, Any, Any, str, Any]:
        if self._models is not None:
            return self._models
        with self._load_lock:
            if self._models is not None:
                return self._models
            if not self.fsmn_model_path.joinpath("model.pt").is_file():
                raise FileNotFoundError(f"FSMN VAD model missing: {self.fsmn_model_path}")
            if not self.audioset_model_path.joinpath("model.safetensors").is_file():
                raise FileNotFoundError(f"AudioSet classifier missing: {self.audioset_model_path}")
            from funasr import AutoModel
            from silero_vad import load_silero_vad
            import torch
            from transformers import AutoFeatureExtractor, ASTForAudioClassification

            ten_vad_class = None
            if self.ten_vad_enabled:
                from ten_vad import TenVad

                ten_vad_class = TenVad

            device = self.device if torch.cuda.is_available() else "cpu"
            fsmn = AutoModel(
                model=str(self.fsmn_model_path),
                device=device,
                disable_update=True,
                check_latest=False,
                disable_pbar=True,
            )
            silero = load_silero_vad(onnx=True)
            feature_extractor = AutoFeatureExtractor.from_pretrained(
                str(self.audioset_model_path),
                local_files_only=True,
            )
            classifier = ASTForAudioClassification.from_pretrained(
                str(self.audioset_model_path),
                local_files_only=True,
            ).to(device).eval()
            self._models = (
                fsmn,
                silero,
                feature_extractor,
                classifier,
                torch,
                device,
                ten_vad_class,
            )
            return self._models


def failed_presence_result(
    *,
    window_id: str,
    audio_evidence_refs: list[str],
    provider: str,
    model: str,
    method_version: str,
    error: Exception,
    latency_ms: int,
) -> dict[str, Any]:
    return {
        "contract_version": PRESENCE_CONTRACT_VERSION,
        "presence_run_id": f"presence-{uuid.uuid4().hex[:16]}",
        "window_id": window_id,
        "status": "failed",
        "presence_class": "unknown",
        "speech_present": None,
        "speech_probability": None,
        "speech_segments": [],
        "non_speech_activity": None,
        "audio_evidence_refs": list(audio_evidence_refs),
        "provider": provider,
        "model": model,
        "method_version": method_version,
        "latency_ms": latency_ms,
        "warnings": [],
        "error": {"type": type(error).__name__, "message": str(error)},
    }


def _completed_result(
    *,
    presence_class: str,
    duration_ms: int,
    rms_dbfs: float,
    segments: list[PresenceSegment],
    speech_probability: float,
    music_probability: float,
    non_speech_activity: bool,
    warnings: list[str],
) -> dict[str, Any]:
    if presence_class not in PRESENCE_CLASSES:
        raise ValueError(f"invalid presence class: {presence_class}")
    return {
        "contract_version": PRESENCE_CONTRACT_VERSION,
        "status": "completed",
        "presence_class": presence_class,
        "speech_present": bool(segments),
        "speech_probability": round(speech_probability, 6),
        "music_probability": round(music_probability, 6),
        "speech_segments": [item.to_dict() for item in segments],
        "speech_coverage": round(
            sum(item.end_ms - item.start_ms for item in segments) / duration_ms,
            6,
        ),
        "non_speech_activity": non_speech_activity,
        "audio_level_dbfs": round(rms_dbfs, 3) if math.isfinite(rms_dbfs) else -120.0,
        "warnings": warnings,
        "error": None,
    }


def _best_classifier_window(
    windows: tuple[ClassifierWindow, ...],
    *,
    start_ms: int,
    end_ms: int,
) -> ClassifierWindow | None:
    overlapping = [
        item
        for item in windows
        if _overlap_ms(start_ms, end_ms, item.start_ms, item.end_ms) > 0
    ]
    return max(overlapping, key=lambda item: item.speech_probability, default=None)


def _overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _merge_segments(segments: list[PresenceSegment]) -> list[PresenceSegment]:
    ordered = sorted(segments, key=lambda item: (item.start_ms, item.end_ms))
    merged: list[PresenceSegment] = []
    for item in ordered:
        if not merged or item.start_ms > merged[-1].end_ms:
            merged.append(item)
            continue
        previous = merged[-1]
        confidences = [
            value
            for value in (previous.confidence, item.confidence)
            if value is not None
        ]
        merged[-1] = PresenceSegment(
            start_ms=previous.start_ms,
            end_ms=max(previous.end_ms, item.end_ms),
            confidence=max(confidences) if confidences else None,
        )
    return merged


def _fsmn_segments(output: Any) -> tuple[tuple[int, int], ...]:
    if not isinstance(output, list) or not output or not isinstance(output[0], dict):
        return ()
    values = output[0].get("value") or []
    segments = []
    for item in values:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            segments.append((int(item[0]), int(item[1])))
    return tuple(segments)


def _ten_vad_segments(
    audio: Any,
    *,
    ten_vad_class: Any,
    sample_rate: int,
    threshold: float,
    min_frames: int,
    hop_size: int = 256,
) -> tuple[tuple[int, int], ...]:
    import numpy as np

    if min_frames <= 0:
        raise ValueError("TEN VAD min_frames must be positive")
    pcm = np.clip(audio * 32768.0, -32768, 32767).astype(np.int16)
    vad = ten_vad_class(hop_size, threshold)
    runs: list[tuple[int, int]] = []
    run_start: int | None = None
    run_frames = 0
    frame_index = 0
    for offset in range(0, len(pcm), hop_size):
        frame = pcm[offset : offset + hop_size]
        if len(frame) < hop_size:
            frame = np.pad(frame, (0, hop_size - len(frame))).astype(np.int16)
        probability, _ = vad.process(frame)
        active = float(probability) >= threshold
        if active:
            if run_start is None:
                run_start = frame_index
            run_frames += 1
        elif run_start is not None:
            if run_frames >= min_frames:
                runs.append((run_start, frame_index))
            run_start = None
            run_frames = 0
        frame_index += 1
    if run_start is not None and run_frames >= min_frames:
        runs.append((run_start, frame_index))
    duration_ms = round(len(pcm) * 1000 / sample_rate)
    return tuple(
        (
            round(start_frame * hop_size * 1000 / sample_rate),
            min(duration_ms, round(end_frame * hop_size * 1000 / sample_rate)),
        )
        for start_frame, end_frame in runs
    )


def _rms_dbfs(audio: Any) -> float:
    import numpy as np

    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
    if rms <= 1e-12:
        return -120.0
    return 20.0 * math.log10(rms)
