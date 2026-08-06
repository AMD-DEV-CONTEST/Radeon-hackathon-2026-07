"""Speech transcription via transformers ASR pipeline (Whisper).

Heavy dependencies (torch, transformers) are imported lazily inside functions
and every failure degrades to a graceful fallback recorded as a warning on the
returned Transcript — never a crash. The transcript JSON contains the full raw
text and is PRIVATE: it is stored as analysis/transcript.private.json and must
never be included in exports or the audit bundle.
"""

from __future__ import annotations

import gc
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Sentence-final punctuation that closes a segment.
_SENTENCE_END = (".", "!", "?")
# A silence gap longer than this (seconds) starts a new segment.
_SEGMENT_GAP_S = 0.8

ProgressCallback = Callable[[float, str], None]

# Module-level pipeline cache so repeated calls reuse the loaded model.
_PIPELINE = None
_PIPELINE_MODEL: str | None = None


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Segment:
    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    language: str = "en"
    has_word_timestamps: bool = True
    warnings: list[str] = field(default_factory=list)


def _progress(cb: Optional[ProgressCallback], frac: float, msg: str) -> None:
    if cb is None:
        return
    try:
        cb(frac, msg)
    except Exception:  # progress reporting must never break the pipeline
        logger.debug("progress callback failed", exc_info=True)


def _resolve_device() -> str:
    """Device from policycut.core.device; RuntimeError from a ROCm
    requirement check must propagate, import problems fall back to cpu."""
    try:
        from policycut.core.device import get_device
    except ImportError:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"
    return get_device()


def _wav_duration_s(wav_path: str | Path) -> float:
    """Duration of a PCM wav via the stdlib; 0.0 on any failure."""
    try:
        import contextlib
        import wave

        with contextlib.closing(wave.open(str(wav_path), "rb")) as wf:
            rate = wf.getframerate()
            return wf.getnframes() / float(rate) if rate else 0.0
    except Exception:
        return 0.0


def _get_pipeline(model_name: str, device: str):
    """Build (or reuse) the transformers ASR pipeline. Raises on failure."""
    global _PIPELINE, _PIPELINE_MODEL
    if _PIPELINE is not None and _PIPELINE_MODEL == model_name:
        return _PIPELINE
    import torch
    from transformers import pipeline as hf_pipeline

    torch_dtype = torch.float16 if device == "cuda" else torch.float32
    logger.info("loading whisper model %s on %s (%s)", model_name, device, torch_dtype)
    _PIPELINE = hf_pipeline(
        "automatic-speech-recognition",
        model=model_name,
        torch_dtype=torch_dtype,
        device=torch.device(device),
    )
    _PIPELINE_MODEL = model_name
    return _PIPELINE


def _parse_word_chunks(chunks: list) -> list[Word]:
    """HF word chunks [{"text","timestamp":(s,e)}] -> sanitized Word list."""
    words: list[Word] = []
    prev_end = 0.0
    for chunk in chunks or []:
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue
        ts = chunk.get("timestamp") or (None, None)
        start = ts[0] if ts[0] is not None else prev_end
        end = ts[1] if len(ts) > 1 and ts[1] is not None else start + 0.3
        start = max(0.0, float(start))
        end = max(start, float(end))
        words.append(Word(text=text, start=start, end=end))
        prev_end = end
    return words


def _group_words(words: list[Word]) -> list[Segment]:
    """Group words into segments at gaps > 0.8s or sentence punctuation."""
    segments: list[Segment] = []
    current: list[Word] = []

    def _flush() -> None:
        if not current:
            return
        segments.append(
            Segment(
                text=" ".join(w.text for w in current),
                start=current[0].start,
                end=current[-1].end,
                words=list(current),
            )
        )
        current.clear()

    for word in words:
        if current:
            gap = word.start - current[-1].end
            if gap > _SEGMENT_GAP_S or current[-1].text.endswith(_SENTENCE_END):
                _flush()
        current.append(word)
    _flush()
    return segments


def transcribe(
    wav_path: str | Path,
    settings,
    progress_cb: Optional[ProgressCallback] = None,
) -> Transcript:
    """Transcribe a wav file into a Transcript with word timestamps.

    Uses the transformers automatic-speech-recognition pipeline with
    ``settings.whisper_model``, return_timestamps="word", chunk_length_s=30,
    fp16 on GPU. Missing dependencies or model failures return an (empty or
    segment-level) Transcript with a warning — never raise, except for an
    explicit ROCm requirement (POLICYCUT_REQUIRE_ROCM) which propagates.
    """
    wav_path = str(wav_path)
    model_name = getattr(settings, "whisper_model", "openai/whisper-large-v3-turbo")
    device = _resolve_device()  # may raise RuntimeError under --require-rocm

    _progress(progress_cb, 0.05, f"Loading ASR model {model_name}")
    try:
        pipe = _get_pipeline(model_name, device)
    except Exception as exc:
        logger.warning("whisper unavailable (%s); skipping transcription", exc)
        return Transcript(
            segments=[],
            language="en",
            has_word_timestamps=False,
            warnings=[f"whisper_unavailable: {type(exc).__name__}"],
        )

    _progress(progress_cb, 0.30, "Transcribing audio (word timestamps)")
    result = None
    word_level = True
    try:
        result = pipe(wav_path, chunk_length_s=30, return_timestamps="word")
    except Exception as exc:
        logger.warning("word-timestamp transcription failed (%s); retrying "
                       "with segment timestamps", exc)
        word_level = False
        try:
            result = pipe(wav_path, chunk_length_s=30, return_timestamps=True)
        except Exception as exc2:
            logger.warning("transcription failed entirely: %s", exc2)
            return Transcript(
                segments=[],
                language="en",
                has_word_timestamps=False,
                warnings=[f"transcription_failed: {type(exc2).__name__}"],
            )

    _progress(progress_cb, 0.85, "Parsing transcription output")
    chunks = (result or {}).get("chunks") or []
    warnings: list[str] = []

    if word_level and chunks:
        words = _parse_word_chunks(chunks)
        if words:
            segments = _group_words(words)
            _progress(progress_cb, 1.0, f"Transcribed {len(segments)} segments")
            return Transcript(segments=segments, language="en",
                              has_word_timestamps=True, warnings=warnings)
        word_level = False

    # Segment-level fallback: chunks are segments (or a single flat text).
    segments = []
    if chunks:
        prev_end = 0.0
        for chunk in chunks:
            text = str(chunk.get("text", "")).strip()
            if not text:
                continue
            ts = chunk.get("timestamp") or (None, None)
            start = float(ts[0]) if ts[0] is not None else prev_end
            end = (float(ts[1]) if len(ts) > 1 and ts[1] is not None
                   else start + max(1.0, 0.35 * len(text.split())))
            end = max(end, start)
            segments.append(Segment(text=text, start=start, end=end, words=[]))
            prev_end = end
    else:
        full_text = str((result or {}).get("text", "")).strip()
        if full_text:
            duration = _wav_duration_s(wav_path)
            segments.append(Segment(text=full_text, start=0.0,
                                    end=duration or 1.0, words=[]))

    warnings.append("segment_level_timestamps")
    logger.warning("word timestamps unavailable; using segment-level timestamps")
    _progress(progress_cb, 1.0, f"Transcribed {len(segments)} segments (segment-level)")
    return Transcript(segments=segments, language="en",
                      has_word_timestamps=False, warnings=warnings)


def save_transcript(transcript: Transcript, path: str | Path) -> Path:
    """Atomically write the transcript JSON (PRIVATE — never exported)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "language": transcript.language,
        "has_word_timestamps": transcript.has_word_timestamps,
        "warnings": list(transcript.warnings),
        "segments": [asdict(seg) for seg in transcript.segments],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)
    logger.info("saved transcript: %d segments -> %s",
                len(transcript.segments), path.name)
    return path


def load_transcript(path: str | Path) -> Transcript | None:
    """Load a transcript JSON written by save_transcript; None if missing."""
    path = Path(path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = []
    for seg in data.get("segments", []):
        words = [Word(text=w["text"], start=float(w["start"]), end=float(w["end"]))
                 for w in seg.get("words", [])]
        segments.append(Segment(text=seg.get("text", ""),
                                start=float(seg.get("start", 0.0)),
                                end=float(seg.get("end", 0.0)),
                                words=words))
    return Transcript(
        segments=segments,
        language=data.get("language", "en"),
        has_word_timestamps=bool(data.get("has_word_timestamps", False)),
        warnings=list(data.get("warnings", [])),
    )


def unload_whisper() -> None:
    """Free the cached ASR pipeline and release GPU memory."""
    global _PIPELINE, _PIPELINE_MODEL
    _PIPELINE = None
    _PIPELINE_MODEL = None
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    logger.info("whisper pipeline unloaded")
