"""Local, offline speech-to-text using openai-whisper (no cloud API).

This is the default STT backend for the diary app's "everything locally
inferred" deployment. The model weights are loaded from ``models/tiny.pt``
(which is shipped in the repo, so no HuggingFace download is required at
runtime).

Set ``DIARY_STT=cloud`` (and a ``QWEN_API_KEY``) to fall back to the cloud
Qwen Omni STT instead.
"""

import logging
import os
import shutil

import whisper
from utils.timing import timing

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(REPO_ROOT, "models")
# openai-whisper expects the checkpoint named exactly "<size>.pt".
MODEL_PATH = os.path.join(MODEL_DIR, "tiny.pt")
MODEL_SRC = os.path.join(MODEL_DIR, "whisper-tiny.pt")

_MODEL = None  # lazily loaded singleton


def _ensure_model_file() -> bool:
    """Make sure ``tiny.pt`` exists (copy from the shipped ``whisper-tiny.pt``)."""
    if os.path.exists(MODEL_PATH):
        return True
    if os.path.exists(MODEL_SRC):
        shutil.copy(MODEL_SRC, MODEL_PATH)
        return True
    return False


def _get_model():
    global _MODEL
    if _MODEL is None:
        if not _ensure_model_file():
            raise FileNotFoundError(
                f"Whisper tiny model not found at {MODEL_PATH} "
                f"(nor source {MODEL_SRC})"
            )
        # CPU is used deliberately: the GPU is already busy with the diary
        # LLM and the image service, and tiny on CPU is fast enough for
        # short utterances.
        _MODEL = whisper.load_model("tiny", download_root=MODEL_DIR, device="cpu")
    return _MODEL


@timing(name="stt_local_transcribe")
def transcribe(filepath: str) -> str:
    """Transcribe a WAV file to text using the local Whisper-tiny model.

    Returns a bracketed sentinel (e.g. ``[local STT unavailable: ...]``) on any
    failure so callers can treat it as "no usable transcript" and avoid feeding
    garbage to the diary agent.
    """
    try:
        model = _get_model()
    except Exception as e:  # model missing / import/runtime error
        logger.error("local whisper load failed: %s", e)
        return f"[local STT unavailable: {e}]"

    try:
        # Read the WAV with soundfile (no ffmpeg needed) and hand Whisper a
        # float32 array — it accepts ndarrays directly, skipping its ffmpeg
        # decode step entirely. Whisper expects 16 kHz mono in [-1, 1].
        import numpy as np
        import soundfile as sf

        data, sr = sf.read(filepath, dtype="float32", always_2d=False)
        if data.ndim > 1:  # downmix stereo -> mono
            data = data.mean(axis=1)
        if sr != 16000:
            data = _resample(data, sr, 16000)
            sr = 16000

        # language=None -> auto-detect (handles zh/en mixed input).
        result = model.transcribe(data, language=None, fp16=False,
                                   beam_size=1, best_of=1)
        text = (result.get("text") or "").strip()
        logger.info("STT(local): %s", text)
        return text
    except Exception as e:
        logger.error("local STT failed: %s", e)
        return f"[语音识别失败: {e}]"


def _resample(data: "np.ndarray", sr_in: int, sr_out: int) -> "np.ndarray":
    """Minimal resample (linear) so we don't depend on ffmpeg/scipy being present."""
    import numpy as np
    n_out = int(round(len(data) * sr_out / sr_in))
    if n_out == len(data):
        return data
    x_old = np.linspace(0, 1, len(data), endpoint=False)
    x_new = np.linspace(0, 1, n_out, endpoint=False)
    return np.interp(x_new, x_old, data).astype("float32")
