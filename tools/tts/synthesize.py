from contextlib import redirect_stdout
import logging
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import List, Optional

from tools.tts.cleaner import clean_for_tts, split_sentences

logger = logging.getLogger("tools.tts.synthesize")
if not logger.handlers:
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(name)s: %(message)s")

SAMPLES_DIR = Path(__file__).parent / "samples"
VOICES = {
    "female": SAMPLES_DIR / "voice_female.wav",
    "male": SAMPLES_DIR / "voice_male.wav",
    "narrator": SAMPLES_DIR / "voice_narrator.wav",
    "default": SAMPLES_DIR / "voice_narrator.wav",
}
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
CHUNK_MAX_CHARS = 220
MAX_OOM_SPLITS = 3
WORDS_PER_SECOND_ESTIMATE = 2.5


class SynthesisError(RuntimeError):
    pass


def list_voices() -> List[str]:
    return [name for name in VOICES if name != "default"]


def _resolve_voice(voice: str) -> Path:
    if voice in VOICES:
        path = VOICES[voice]
        if not path.is_file():
            raise SynthesisError(
                f"Voice sample missing on disk: {path}. "
                f"Expected default voices under {SAMPLES_DIR}."
            )
        return path
    custom_path = Path(voice)
    if custom_path.is_file():
        return custom_path
    raise SynthesisError(
        f"Unknown voice {voice!r}. Available: {', '.join(list_voices())}, "
        "or pass a path to a custom voice sample."
    )


def _wav_duration(path: str) -> float:
    try:
        with wave.open(path, "rb") as f:
            frames = f.getnframes()
            rate = f.getframerate()
            return round(frames / float(rate), 2) if rate else 0.0
    except (wave.Error, EOFError):
        return 0.0


def _write_silence(output_path: str, duration: float) -> None:
    duration = max(0.5, duration)
    if shutil.which("ffmpeg"):
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
            "-t", f"{duration:.2f}", output_path,
        ]
        #result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        result = subprocess.run(cmd, text=True, timeout=30)
        if result.returncode == 0:
            return
        logger.warning("ffmpeg silence fallback failed: %s", result.stderr.strip()[-300:])

    # Last-resort pure-Python fallback: write silent PCM frames directly.
    rate = 24000
    n_frames = int(rate * duration)
    with wave.open(output_path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\x00\x00" * n_frames)


def _concat_audio(parts: List[str], output_path: str) -> None:
    if len(parts) == 1:
        shutil.copyfile(parts[0], output_path)
        return

    if shutil.which("ffmpeg"):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as list_file:
            for p in parts:
                safe = os.path.abspath(p).replace("'", "'\\''")
                list_file.write(f"file '{safe}'\n")
            list_path = list_file.name
        try:
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path]
            #result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            result = subprocess.run(cmd, text=True, timeout=60)
            if result.returncode == 0:
                return
            logger.warning("ffmpeg concat failed, falling back to raw wave join: %s", result.stderr.strip()[-300:])
        finally:
            os.remove(list_path)

    try:
        with wave.open(parts[0], "rb") as first:
            params = first.getparams()
        with wave.open(output_path, "wb") as out:
            out.setparams(params)
            for p in parts:
                with wave.open(p, "rb") as part:
                    out.writeframes(part.readframes(part.getnframes()))
    except wave.Error as exc:
        raise SynthesisError(f"Could not concatenate audio parts: {exc}") from exc


class Synthesizer:
    def __init__(self, device: Optional[str] = None):
        try:
            import torch  # type: ignore[import-not-found]
            from TTS.api import TTS  # type: ignore[import-not-found]
            
            _original_load = torch.load
            
            def _patched_load(*args, **kwargs):
                kwargs['weights_only'] = False
                return _original_load(*args, **kwargs)
                
            torch.load = _patched_load
            
        except ImportError as exc:
            raise SynthesisError(
                "The 'TTS' package (Coqui XTTS v2) is not installed. Run `pip install TTS`."
            ) from exc

        resolved_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        if resolved_device == "cpu":
            logger.warning("No GPU detected; running XTTS on CPU (much slower).")

        print("Initializing Synthesizer with model:", MODEL_NAME, "on device:", resolved_device, flush=True)
        self._torch = torch

        print("Torch imported", flush=True)
        import os
        from contextlib import redirect_stdout
        #with open(os.devnull, 'w') as f, redirect_stdout(f):
        self._tts = TTS(MODEL_NAME).to(resolved_device)

        print("Synthesizer initialized with model:", MODEL_NAME, "on device:", resolved_device, flush=True)

    def _tts_to_file(self, text: str, output_path: str, speaker_wav: str, language: str) -> None:
        """ self._tts.tts_to_file(
            text=text, file_path=output_path, speaker_wav=speaker_wav, language=language,
        ) """

        with open(os.devnull, 'w') as f, redirect_stdout(f):
            self._tts.tts_to_file(
                text=text, file_path=output_path, speaker_wav=speaker_wav, language=language,
            )

    def _synthesize_with_retry(self, text: str, output_path: str, speaker_wav: str, language: str, depth: int = 0) -> None:
        try:
            self._tts_to_file(text, output_path, speaker_wav, language)
        except RuntimeError as exc:
            if "out of memory" in str(exc).lower() and depth < MAX_OOM_SPLITS and len(text) > 20:
                logger.warning("OOM during synthesis (depth %d); splitting text and retrying.", depth)
                if hasattr(self._torch, "cuda") and self._torch.cuda.is_available():
                    self._torch.cuda.empty_cache()

                midpoint = len(text) // 2
                split_at = text.rfind(" ", 0, midpoint)
                if split_at <= 0:
                    split_at = midpoint
                first_half, second_half = text[:split_at].strip(), text[split_at:].strip()

                part_a = f"{output_path}.part{depth}a.wav"
                part_b = f"{output_path}.part{depth}b.wav"
                self._synthesize_with_retry(first_half, part_a, speaker_wav, language, depth + 1)
                self._synthesize_with_retry(second_half, part_b, speaker_wav, language, depth + 1)
                _concat_audio([part_a, part_b], output_path)
                os.remove(part_a)
                os.remove(part_b)
                return
            raise SynthesisError(f"TTS synthesis failed: {exc}") from exc

        if not Path(output_path).is_file() or Path(output_path).stat().st_size == 0:
            logger.warning("Synthesis produced an empty file; retrying once.")
            try:
                self._tts_to_file(text, output_path, speaker_wav, language)
            except RuntimeError as exc:
                raise SynthesisError(f"TTS synthesis failed on retry: {exc}") from exc

            if not Path(output_path).is_file() or Path(output_path).stat().st_size == 0:
                logger.warning("Still empty after retry; writing a silent placeholder track.")
                estimated_duration = max(1.0, len(text.split()) / WORDS_PER_SECOND_ESTIMATE)
                _write_silence(output_path, estimated_duration)

    def synthesize(self, text: str, output_path: str, voice: str = "default", language: str = "en") -> str:
        cleaned = clean_for_tts(text)
        if not cleaned:
            raise SynthesisError("No speakable text remained after cleaning the input.")

        speaker_wav = str(_resolve_voice(voice))
        output_path_obj = Path(output_path)
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)

        chunks = split_sentences(cleaned, max_chars=CHUNK_MAX_CHARS) if len(cleaned) > CHUNK_MAX_CHARS else [cleaned]

        if len(chunks) == 1:
            self._synthesize_with_retry(chunks[0], str(output_path_obj), speaker_wav, language)
            return str(output_path_obj)

        workdir = tempfile.mkdtemp(prefix="edumanim_tts_")
        try:
            chunk_paths = []
            for i, chunk in enumerate(chunks):
                chunk_path = os.path.join(workdir, f"chunk_{i:03d}.wav")
                logger.info("Synthesizing chunk %d/%d", i + 1, len(chunks))
                self._synthesize_with_retry(chunk, chunk_path, speaker_wav, language)
                chunk_paths.append(chunk_path)
            _concat_audio(chunk_paths, str(output_path_obj))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        return str(output_path_obj)

    def preview(self, voice: str, output_path: str) -> str:
        sample_text = f"This is a preview of the {voice} voice for EduManim."
        return self.synthesize(sample_text, output_path, voice=voice)