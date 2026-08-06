"""Audio recording using pyaudio.

pyaudio is an optional dependency (installed via the ``voice`` extra). It is
imported lazily so this module can be imported even when microphone support is
not installed (e.g. in CI or headless environments).
"""

import logging
import sys
import time
import wave
from pathlib import Path

from utils.timing import timing

logger = logging.getLogger(__name__)

CHUNK = 1024
CHANNELS = 1


def _audio_format() -> int:
    """Lazily import pyaudio and return the 16-bit PCM format constant."""
    import pyaudio

    return pyaudio.paInt16


def _get_sample_rate(p) -> int:
    """Get supported sample rate (try 16000 first, fall back to device native)."""
    try:
        dev = p.get_default_input_device_info()
        native = int(dev["defaultSampleRate"])
        for rate in [16000, 8000, native]:
            if p.is_format_supported(
                rate,
                input_device=dev["index"],
                input_channels=1,
                input_format=_audio_format(),
            ):
                return rate
    except Exception:
        pass
    return 16000


@timing(name="record_audio")
def record(filepath: str, duration: float = 5.0) -> str:
    """Record audio from microphone for a fixed duration.

    Shows a countdown so the user knows how long to speak.

    If recording hangs (no mic permission), falls back to a warning message.
    """
    import pyaudio

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    p = pyaudio.PyAudio()
    rate = _get_sample_rate(p)

    logger.info("Using sample rate: %d Hz", rate)

    try:
        stream = p.open(
            format=_audio_format(),
            channels=CHANNELS,
            rate=rate,
            input=True,
            frames_per_buffer=CHUNK,
            stream_callback=None,
        )
    except OSError as e:
        p.terminate()
        logger.error("Cannot open microphone: %s", e)
        print("\n[Cannot access microphone - check System Settings > Privacy > Microphone]")
        return _create_silent_wav(filepath, rate, duration)

    frames: list[bytes] = []

    total_chunks = int(rate / CHUNK * duration)
    last_sec = -1
    start = time.time()

    for i in range(total_chunks):
        elapsed = time.time() - start
        remaining = int(duration - elapsed)
        if remaining != last_sec and remaining >= 0:
            sys.stdout.write(f"\r[Recording... {remaining}s remaining] ")
            sys.stdout.flush()
            last_sec = remaining

        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
        except Exception as e:
            logger.error("Read error: %s", e)
            break

    print("\r[Done recording]" + " " * 30)
    stream.stop_stream()
    stream.close()
    p.terminate()

    _save_wav(filepath, rate, p.get_sample_size(_audio_format()), frames)
    actual_dur = len(frames) * CHUNK / rate if rate > 0 else 0
    logger.info("Saved %s (%.1fs, %d Hz)", filepath, actual_dur, rate)
    return filepath


def _save_wav(filepath: str, rate: int, sample_width: int, frames: list[bytes]):
    wf = wave.open(filepath, "wb")
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(sample_width)
    wf.setframerate(rate)
    wf.writeframes(b"".join(frames))
    wf.close()


def _create_silent_wav(filepath: str, rate: int, duration: float) -> str:
    """Create a silent WAV file as a placeholder."""
    num_bytes = int(rate * duration * 2)  # 16-bit = 2 bytes per sample
    wf = wave.open(filepath, "wb")
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)
    wf.setframerate(rate)
    wf.writeframes(b"\x00\x00" * (num_bytes // 2))
    wf.close()
    return filepath
