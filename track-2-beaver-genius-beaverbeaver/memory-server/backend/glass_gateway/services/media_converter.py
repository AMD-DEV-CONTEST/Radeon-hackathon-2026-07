from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave

from glass_gateway.domain.meeting import StoredEvidence


_SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]+$")

# ffmpeg must never wedge the worker. A hung conversion on a slow storage
# mount previously blocked the whole event loop; the timeout bounds the
# subprocess and callers additionally run conversions via asyncio.to_thread.
_FFMPEG_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class PreparedMedia:
    path: Path
    uri: str
    media_type: str
    captured_at_ms: int


class MediaConverter:
    def __init__(
        self,
        raw_media_root: str | Path,
        *,
        audio_filter: str | None = None,
    ) -> None:
        self.root = Path(raw_media_root).resolve()
        self.audio_filter = audio_filter

    def pcm_chunks_to_wav(
        self,
        user_id: str,
        stream_id: str,
        chunks: list[StoredEvidence],
        *,
        sample_rate: int,
    ) -> PreparedMedia:
        if not chunks:
            raise ValueError("at least one PCM chunk is required")
        safe_user = self._safe_part(user_id)
        safe_stream = self._safe_part(stream_id)
        ordered = sorted(chunks, key=lambda item: item.path.name)
        for chunk in ordered:
            self._require_inside_root(chunk.path)

        output = self.root / safe_user / safe_stream / "derived" / f"{safe_stream}.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.stem}-raw-",
            suffix=".wav",
            delete=False,
        ) as handle:
            raw_temp = Path(handle.name)
        filtered_temp: Path | None = None
        try:
            with wave.open(str(raw_temp), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                for chunk in ordered:
                    wav.writeframes(chunk.path.read_bytes())
            if self.audio_filter:
                with tempfile.NamedTemporaryFile(
                    dir=output.parent,
                    prefix=f".{output.stem}-filtered-",
                    suffix=".wav",
                    delete=False,
                ) as handle:
                    filtered_temp = Path(handle.name)
                subprocess.run(
                    [
                        "ffmpeg",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(raw_temp),
                        "-af",
                        self.audio_filter,
                        "-ar",
                        str(sample_rate),
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        str(filtered_temp),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=_FFMPEG_TIMEOUT_SECONDS,
                )
                os.replace(filtered_temp, output)
            else:
                os.replace(raw_temp, output)
        finally:
            raw_temp.unlink(missing_ok=True)
            if filtered_temp is not None:
                filtered_temp.unlink(missing_ok=True)

        return PreparedMedia(
            path=output,
            uri=output.resolve().as_uri(),
            media_type="audio/wav",
            captured_at_ms=ordered[0].captured_at_ms,
        )

    def wav_to_pcm(self, media: PreparedMedia) -> tuple[bytes, int]:
        self._require_inside_root(media.path)
        with wave.open(str(media.path), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError("expected mono 16-bit WAV")
            return wav.readframes(wav.getnframes()), wav.getframerate()

    def nv12_to_jpeg(
        self,
        evidence: StoredEvidence,
        *,
        width: int,
        height: int,
    ) -> PreparedMedia:
        self._require_inside_root(evidence.path)
        expected_bytes = width * height * 3 // 2
        if evidence.bytes != expected_bytes:
            raise ValueError(
                f"invalid NV12 size: expected {expected_bytes}, got {evidence.bytes}"
            )

        output_dir = evidence.path.parent.parent / "derived"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{evidence.path.stem}.jpg"
        with tempfile.NamedTemporaryFile(
            dir=output_dir,
            prefix=f".{output.stem}-",
            suffix=".jpg",
            delete=False,
        ) as handle:
            temp = Path(handle.name)

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "rawvideo",
                    "-pixel_format",
                    "nv12",
                    "-video_size",
                    f"{width}x{height}",
                    "-i",
                    str(evidence.path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(temp),
                ],
                check=True,
                capture_output=True,
                timeout=_FFMPEG_TIMEOUT_SECONDS,
            )
            os.replace(temp, output)
        finally:
            temp.unlink(missing_ok=True)

        return PreparedMedia(
            path=output,
            uri=output.resolve().as_uri(),
            media_type="image/jpeg",
            captured_at_ms=evidence.captured_at_ms,
        )

    def select_representative_images(
        self,
        images: list[StoredEvidence],
        *,
        interval_ms: int = 30000,
    ) -> list[StoredEvidence]:
        selected: list[StoredEvidence] = []
        last_timestamp: int | None = None
        for image in sorted(images, key=lambda item: item.captured_at_ms):
            if (
                last_timestamp is None
                or image.captured_at_ms - last_timestamp >= interval_ms
            ):
                selected.append(image)
                last_timestamp = image.captured_at_ms
        return selected

    def _require_inside_root(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"evidence is outside raw media root: {path}") from exc

    @staticmethod
    def _safe_part(value: str) -> str:
        if not value or not _SAFE_PART.fullmatch(value):
            raise ValueError(f"unsafe media path part: {value!r}")
        return value
