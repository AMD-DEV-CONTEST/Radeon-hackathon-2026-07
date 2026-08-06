"""Real-time transcription for MedGlass.

Two interchangeable backends:

* ``cli``      - whisper.cpp ``whisper-cli`` subprocess (hipBLAS / ROCm GPU).
                 This is the target deployment path from setup.sh.
* ``pywhispercpp`` - the ``pywhispercpp`` prebuilt wheel (CPU, no compiler
                 needed). Used automatically when the CLI binary is missing
                 so the app runs on any machine.

Backend selection is driven by ``whisper_backend`` in config:
  "auto" (default) -> CLI if present, else pywhispercpp, else error.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from collections import deque
from pathlib import Path

from config import CONFIG
from utils import MedGlassError, write_wav

LOG = logging.getLogger("medglass.audio")


class WhisperBackend:
    """Common interface implemented by the CLI and pywhispercpp backends."""

    def transcribe(self, pcm: bytes) -> str:
        raise NotImplementedError

    def transcribe_segments(self, pcm: bytes) -> list[dict]:
        raise NotImplementedError


class _CLIWhisper(WhisperBackend):
    """whisper.cpp ``whisper-cli`` subprocess backend (hipBLAS on GPU)."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self._bin = Path(cfg["whisper_bin"])
        self._model = Path(cfg["whisper_model"])
        if not self._bin.exists():
            raise MedGlassError(
                f"whisper.cpp binary not found at {self._bin}. "
                "Run setup.sh or set MEDGLASS_WHISPER_BIN."
            )
        if not self._model.exists():
            raise MedGlassError(
                f"whisper model not found at {self._model}. "
                "Download ggml-small.en.bin into models/."
            )

    def _command(self, wav_path: str) -> list[str]:
        cmd = [
            str(self._bin),
            "--file", wav_path,
            "--model", str(self._model),
            "--language", self.cfg["whisper_lang"],
            "--threads", str(self.cfg["whisper_threads"]),
            "--beam-size", str(self.cfg["whisper_beam_size"]),
        ]
        if not self.cfg["whisper_hipblas"]:
            cmd.append("--no-gpu")
        return cmd

    def transcribe_segments(self, pcm: bytes) -> list[dict]:
        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            write_wav(wav_path, pcm, self.cfg["sample_rate"])
            return self._run(wav_path)
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def transcribe(self, pcm: bytes) -> str:
        segs = self.transcribe_segments(pcm)
        return " ".join(s["text"].strip() for s in segs if s.get("text"))

    def _run(self, wav_path: str) -> list[dict]:
        try:
            proc = subprocess.run(
                self._command(wav_path), capture_output=True, text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise MedGlassError("whisper.cpp timed out on window")
        if proc.returncode != 0:
            raise MedGlassError(
                f"whisper.cpp failed ({proc.returncode}): {proc.stderr[:2000]}"
            )
        return self._parse_output(proc.stdout)

    @staticmethod
    def _parse_output(stdout: str) -> list[dict]:
        import re
        # whisper-cli default stdout: "[00:00:00.000 --> 00:00:05.000]   text"
        _SEG_RE = re.compile(
            r"\[\s*(\d+):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*"
            r"(\d+):(\d{2}):(\d{2})\.(\d{3})\]\s*(.*)$")
        segments = []
        for line in stdout.splitlines():
            m = _SEG_RE.match(line.strip())
            if not m:
                continue
            h, mi, s, ms, h2, mi2, s2, ms2, text = m.groups()
            start = ((int(h) * 3600 + int(mi) * 60 + int(s)) * 1000 + int(ms))
            end = ((int(h2) * 3600 + int(mi2) * 60 + int(s2)) * 1000 + int(ms2))
            text = text.strip()
            if text and text != "[BLANK_AUDIO]":
                segments.append({"text": text, "start": start, "end": end})
        return segments


class _PyWhisper(WhisperBackend):
    """pywhispercpp prebuilt-wheel backend (CPU, no compilation needed)."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self._model_path = Path(cfg["whisper_model"])
        if not self._model_path.exists():
            raise MedGlassError(
                f"whisper model not found at {self._model_path}. "
                "Download ggml-small.en.bin into models/."
            )
        try:
            from pywhispercpp.model import Model
        except ImportError as exc:  # pragma: no cover
            raise MedGlassError(
                "pywhispercpp not installed (pip install pywhispercpp)."
            ) from exc
        LOG.info("loading whisper model %s (CPU)", self._model_path)
        self._model = Model(
            str(self._model_path),
            n_threads=max(1, cfg["whisper_threads"]),
            language=cfg["whisper_lang"],
            no_context=True,
            print_progress=False,
        )

    def transcribe(self, pcm: bytes) -> str:
        segs = self.transcribe_segments(pcm)
        return " ".join(s["text"].strip() for s in segs if s.get("text"))

    def transcribe_segments(self, pcm: bytes) -> list[dict]:
        import numpy as np
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return []
        segments = self._model.transcribe(audio)
        return [{"text": s.text.strip(), "start": s.t0, "end": s.t1,
                 "probability": getattr(s, "probability", None)}
                for s in segments if s.text.strip()]


def build_backend(cfg: dict | None = None) -> WhisperBackend:
    """Instantiate the best available whisper backend."""
    cfg = cfg or CONFIG
    mode = cfg.get("whisper_backend", "auto")
    if mode == "cli":
        return _CLIWhisper(cfg)
    if mode == "pywhispercpp":
        return _PyWhisper(cfg)
    # auto
    if Path(cfg["whisper_bin"]).exists():
        LOG.info("whisper backend: cli (ROCm)")
        return _CLIWhisper(cfg)
    try:
        import pywhispercpp  # noqa: F401
    except ImportError:
        pass
    else:
        LOG.info("whisper backend: pywhispercpp (CPU)")
        return _PyWhisper(cfg)
    raise MedGlassError(
        "no whisper backend available. Install pywhispercpp or build "
        "whisper.cpp (see setup.sh)."
    )


class WhisperTranscriber:
    """Convenience facade kept for API compatibility with older callers."""

    def __init__(self, cfg: dict | None = None, backend: WhisperBackend | None = None):
        self.cfg = cfg or CONFIG
        self.backend = backend or build_backend(self.cfg)

    @property
    def _bin(self) -> Path:
        return Path(self.cfg["whisper_bin"])

    def transcribe(self, pcm: bytes) -> str:
        return self.backend.transcribe(pcm)

    def transcribe_json(self, pcm: bytes) -> list[dict]:
        return self.backend.transcribe_segments(pcm)


class ChunkBuffer:
    """Rolling byte buffer that emits overlapping audio windows.

    Keeps only the most recent `window_seconds` of audio plus `overlap`
    seconds, so words spanning window boundaries are re-seen in the next
    window and nothing is ever dropped mid-utterance.
    """

    def __init__(self, sample_rate: int, window_seconds: float,
                 overlap_seconds: float) -> None:
        self.sample_rate = sample_rate
        self.window = int(sample_rate * window_seconds)
        self.overlap = int(sample_rate * overlap_seconds)
        self.max_bytes = (self.window + self.overlap) * 2
        self._chunks: deque[bytes] = deque()
        self._len = 0

    def push(self, chunk: bytes) -> None:
        self._chunks.append(chunk)
        self._len += len(chunk)
        while self._len > self.max_bytes:
            head = self._chunks.popleft()
            self._len -= len(head)

    def window_bytes(self) -> bytes:
        """Most recent full window of PCM (trimmed to `window_seconds`)."""
        data = b"".join(self._chunks)
        return data[-self.window * 2:]

    def tail_bytes(self, seconds: float) -> bytes:
        """Trailing `seconds` of audio, e.g. for dedup against previous window."""
        n = int(seconds * self.sample_rate) * 2
        return b"".join(self._chunks)[-n:]
