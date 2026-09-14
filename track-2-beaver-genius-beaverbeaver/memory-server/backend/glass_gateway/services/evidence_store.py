from hashlib import sha256
import os
from pathlib import Path
import re
import uuid

from glass_gateway.domain.meeting import StoredEvidence


_SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_part(value: str) -> str:
    if not value or not _SAFE_PART.fullmatch(value):
        raise ValueError(f"unsafe evidence path part: {value!r}")
    return value


def _write_immutable(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise ValueError(f"immutable evidence mismatch: {path.name}")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("xb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        except (AttributeError, OSError):
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


class LocalEvidenceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write_audio_chunk(
        self,
        user_id: str,
        stream_id: str,
        index: int,
        captured_at_ms: int,
        body: bytes,
        *,
        device_monotonic_ms: int | None = None,
        server_received_at_ms: int | None = None,
        server_anchor_ms: int | None = None,
        device_monotonic_anchor_ms: int | None = None,
        timezone_name: str = "Asia/Shanghai",
        capture_time_source: str = "server_received_fallback",
        device_id: str | None = None,
        boot_id: str | None = None,
        media_stream_id: str | None = None,
        captured_at_device_ms: int | None = None,
        clock_synced: bool | None = None,
        duration_ms: int = 0,
        clock_anomaly: bool = False,
        clock_deviation_ms: int | None = None,
    ) -> StoredEvidence:
        safe_user = _validate_part(user_id)
        safe_stream = _validate_part(stream_id)
        digest = sha256(body).hexdigest()
        path = (
            self.root
            / safe_user
            / safe_stream
            / "audio"
            / f"{index:09d}-{digest[:12]}.pcm"
        )
        _write_immutable(path, body)
        return StoredEvidence(
            evidence_id=f"aud_{safe_stream}_{index}_{digest[:12]}",
            media_type="audio/pcm_s16le",
            path=path,
            captured_at_ms=captured_at_ms,
            sha256=digest,
            bytes=len(body),
            device_monotonic_ms=device_monotonic_ms,
            server_received_at_ms=server_received_at_ms,
            server_anchor_ms=server_anchor_ms,
            device_monotonic_anchor_ms=device_monotonic_anchor_ms,
            timezone_name=timezone_name,
            capture_time_source=capture_time_source,
            device_id=device_id,
            boot_id=boot_id,
            stream_id=media_stream_id or stream_id,
            sequence=index,
            captured_at_device_ms=captured_at_device_ms,
            clock_synced=clock_synced,
            duration_ms=duration_ms,
            clock_anomaly=clock_anomaly,
            clock_deviation_ms=clock_deviation_ms,
        )

    def write_image(
        self,
        user_id: str,
        stream_id: str,
        index: int,
        captured_at_ms: int,
        suffix: str,
        body: bytes,
        *,
        device_monotonic_ms: int | None = None,
        server_received_at_ms: int | None = None,
        server_anchor_ms: int | None = None,
        device_monotonic_anchor_ms: int | None = None,
        timezone_name: str = "Asia/Shanghai",
        capture_time_source: str = "server_received_fallback",
        device_id: str | None = None,
        boot_id: str | None = None,
        media_stream_id: str | None = None,
        captured_at_device_ms: int | None = None,
        clock_synced: bool | None = None,
        duration_ms: int = 0,
        clock_anomaly: bool = False,
        clock_deviation_ms: int | None = None,
    ) -> StoredEvidence:
        safe_user = _validate_part(user_id)
        safe_stream = _validate_part(stream_id)
        safe_suffix = _validate_part(suffix.lower())
        digest = sha256(body).hexdigest()
        path = (
            self.root
            / safe_user
            / safe_stream
            / "images"
            / f"{index:09d}-{captured_at_ms}-{digest[:12]}.{safe_suffix}"
        )
        _write_immutable(path, body)
        return StoredEvidence(
            evidence_id=f"img_{safe_stream}_{index}_{digest[:12]}",
            media_type=f"image/{safe_suffix}",
            path=path,
            captured_at_ms=captured_at_ms,
            sha256=digest,
            bytes=len(body),
            device_monotonic_ms=device_monotonic_ms,
            server_received_at_ms=server_received_at_ms,
            server_anchor_ms=server_anchor_ms,
            device_monotonic_anchor_ms=device_monotonic_anchor_ms,
            timezone_name=timezone_name,
            capture_time_source=capture_time_source,
            device_id=device_id,
            boot_id=boot_id,
            stream_id=media_stream_id or stream_id,
            sequence=index,
            captured_at_device_ms=captured_at_device_ms,
            clock_synced=clock_synced,
            duration_ms=duration_ms,
            clock_anomaly=clock_anomaly,
            clock_deviation_ms=clock_deviation_ms,
        )
