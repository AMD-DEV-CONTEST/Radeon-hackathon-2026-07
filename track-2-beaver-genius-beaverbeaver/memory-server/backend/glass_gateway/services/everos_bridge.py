from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse
import wave
from typing import Any, Protocol

from glass_gateway.domain.meeting import StoredEvidence
from glass_gateway.integrations.everos import EverOSError
from glass_gateway.services.media_converter import MediaConverter


_SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


class EverOSMemoryAPI(Protocol):
    async def add_messages(
        self,
        session_id: str,
        messages: list[dict],
    ) -> dict: ...

    async def flush(self, session_id: str) -> dict: ...


class AudioTranscriber(Protocol):
    async def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str: ...


class TranscriptionUnavailableError(RuntimeError):
    pass


TRANSCRIPTION_RETRY_BACKOFF_MS = 5 * 60 * 1000
DEFAULT_RETRY_BACKOFF_MS = 60 * 1000


class EverOSMeetingBridge:
    def __init__(
        self,
        *,
        raw_media_root: str | Path,
        converter: MediaConverter,
        everos: EverOSMemoryAPI,
        audio_transcriber: AudioTranscriber | None = None,
        transcription_chunk_bytes: int = 960_000,
    ) -> None:
        self.root = Path(raw_media_root).resolve()
        self.converter = converter
        self.everos = everos
        self.audio_transcriber = audio_transcriber
        self.transcription_chunk_bytes = transcription_chunk_bytes
        self._retry_task: asyncio.Task | None = None

    async def close_window(
        self,
        *,
        session_id: str,
        user_id: str,
        sender_name: str,
        audio_chunks: list[StoredEvidence],
        images: list[StoredEvidence],
        sample_rate: int,
        image_width: int,
        image_height: int,
        window_metadata: dict[str, Any] | None = None,
    ) -> dict:
        safe_session = self._safe_part(session_id)
        safe_user = self._safe_part(user_id)
        if not audio_chunks:
            raise ValueError("cannot bridge a window without audio")

        manifest_path = (
            self.root / safe_user / safe_session / "bridge-manifest.json"
        )
        manifest = self._load_manifest(manifest_path)

        if manifest.get("state") == "flushed":
            return {
                "status": "flushed",
                "everos": manifest["flush_response"],
                "media_uris": manifest["media_uris"],
                "manifest": str(manifest_path),
            }

        if manifest:
            result = await self._submit_manifest(manifest_path, manifest)
            if result.get("status") == "pending":
                self._schedule_retry()
            return result

        wav = await asyncio.to_thread(
            self.converter.pcm_chunks_to_wav,
            safe_user,
            safe_session,
            audio_chunks,
            sample_rate=sample_rate,
        )
        representative_images = self.converter.select_representative_images(images)
        prepared_images = await asyncio.gather(
            *(
                asyncio.to_thread(
                    self.converter.nv12_to_jpeg,
                    image,
                    width=image_width,
                    height=image_height,
                )
                for image in representative_images
            )
        )

        media_uris = [wav.uri, *(image.uri for image in prepared_images)]
        try:
            content = await self._build_content(
                safe_session=safe_session,
                wav_uri=wav.uri,
                wav_name=wav.path.name,
                audio_chunks=audio_chunks,
                prepared_images=prepared_images,
                sample_rate=sample_rate,
            )
        except TranscriptionUnavailableError as exc:
            content = self._build_audio_content(
                wav_uri=wav.uri,
                wav_name=wav.path.name,
                audio_chunks=audio_chunks,
                prepared_images=prepared_images,
            )
            manifest = {
                "version": 2,
                "state": "pending",
                "session_id": safe_session,
                "message": {
                    "sender_id": safe_user,
                    "sender_name": sender_name,
                    "role": "user",
                    "timestamp": min(item.captured_at_ms for item in audio_chunks),
                    "content": content,
                },
                "media_uris": media_uris,
                "clock": dict(window_metadata or {}),
                "source_evidence": self._source_evidence(audio_chunks, images),
                "last_attempt_ms": self._now_ms(),
                "last_error": self._serialize_error(exc),
            }
            self._write_manifest(manifest_path, manifest)
            self._schedule_retry()
            return {
                "status": "pending",
                "state": "pending",
                "everos": manifest["last_error"],
                "media_uris": media_uris,
                "manifest": str(manifest_path),
            }
        message = {
            "sender_id": safe_user,
            "sender_name": sender_name,
            "role": "user",
            "timestamp": min(item.captured_at_ms for item in audio_chunks),
            "content": content,
        }

        manifest = {
            "version": 2,
            "state": "pending",
            "session_id": safe_session,
            "message": message,
            "media_uris": media_uris,
            "clock": dict(window_metadata or {}),
            "source_evidence": self._source_evidence(audio_chunks, images),
            "last_attempt_ms": None,
            "last_error": None,
        }
        self._write_manifest(manifest_path, manifest)

        result = await self._submit_manifest(manifest_path, manifest)
        if result.get("status") == "pending":
            self._schedule_retry()
        return result

    @staticmethod
    def _source_evidence(
        audio_chunks: list[StoredEvidence],
        images: list[StoredEvidence],
    ) -> dict[str, list[dict[str, Any]]]:
        def serialize(item: StoredEvidence) -> dict[str, Any]:
            return {
                "id": item.evidence_id,
                "media_type": item.media_type,
                "path": str(item.path.resolve()),
                "captured_at_ms": item.captured_at_ms,
                "device_monotonic_ms": item.device_monotonic_ms,
                "server_received_at_ms": item.server_received_at_ms,
                "server_anchor_ms": item.server_anchor_ms,
                "device_monotonic_anchor_ms": item.device_monotonic_anchor_ms,
                "timezone_name": item.timezone_name,
                "capture_time_source": item.capture_time_source,
            }

        return {
            "audio_chunks": [serialize(item) for item in audio_chunks],
            "images": [serialize(item) for item in images],
        }

    async def retry_pending_once(self) -> int:
        retried = 0
        for manifest_path in sorted(self.root.glob("*/**/bridge-manifest.json")):
            manifest = self._load_manifest(manifest_path)
            if manifest.get("state") not in {"pending", "added"}:
                continue
            if not self._should_retry_manifest(manifest):
                continue
            await self._submit_manifest(manifest_path, manifest)
            retried += 1
        return retried

    def start_retry_loop(self) -> None:
        self._schedule_retry()

    async def stop_retry_loop(self) -> None:
        task = self._retry_task
        self._retry_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _submit_manifest(self, manifest_path: Path, manifest: dict) -> dict:
        try:
            await self._migrate_manifest_to_text(manifest_path, manifest)
            if manifest.get("state") == "pending":
                add_response = await self.everos.add_messages(
                    manifest["session_id"],
                    [manifest["message"]],
                )
                manifest["state"] = "added"
                manifest["add_response"] = add_response
                manifest["last_error"] = None
                manifest["last_attempt_ms"] = self._now_ms()
                self._write_manifest(manifest_path, manifest)

            if manifest.get("state") == "added":
                flush_response = await self.everos.flush(manifest["session_id"])
                manifest["state"] = "flushed"
                manifest["flush_response"] = flush_response
                manifest["last_error"] = None
                manifest["last_attempt_ms"] = self._now_ms()
                self._write_manifest(manifest_path, manifest)
                return {
                    "status": "flushed",
                    "everos": flush_response,
                    "media_uris": manifest["media_uris"],
                    "manifest": str(manifest_path),
                }
        except Exception as exc:
            manifest["last_error"] = self._serialize_error(exc)
            manifest["last_attempt_ms"] = self._now_ms()
            self._write_manifest(manifest_path, manifest)
            return {
                "status": "pending",
                "state": manifest.get("state", "pending"),
                "everos": {"error": str(exc), **manifest["last_error"]},
                "media_uris": manifest["media_uris"],
                "manifest": str(manifest_path),
            }

        return {
            "status": "pending",
            "state": manifest.get("state", "pending"),
            "everos": {"state": manifest.get("state")},
            "media_uris": manifest["media_uris"],
            "manifest": str(manifest_path),
        }

    async def _migrate_manifest_to_text(self, manifest_path: Path, manifest: dict) -> None:
        if self.audio_transcriber is None:
            return
        if manifest.get("state") != "pending":
            return
        message = manifest.get("message") or {}
        content = message.get("content")
        if not isinstance(content, list):
            return
        if content and all(item.get("type") == "text" for item in content if isinstance(item, dict)):
            return

        audio_item = next(
            (
                item
                for item in content
                if isinstance(item, dict) and item.get("type") == "audio" and item.get("uri")
            ),
            None,
        )
        if not audio_item:
            return

        pcm_bytes, sample_rate = self._read_wav_uri(audio_item["uri"])
        transcript = await self._transcribe_pcm_bytes(pcm_bytes, sample_rate)
        if not transcript:
            raise TranscriptionUnavailableError(
                f"ASR returned no usable text for session {manifest.get('session_id')}"
            )

        media_uris = manifest.get("media_uris") or [audio_item["uri"]]
        message["content"] = [
            {
                "type": "text",
                "text": (
                    f"Beaver Memory 记忆窗口 {manifest.get('session_id')}。\n"
                    f"转写内容：\n{transcript}\n\n"
                    f"raw_audio_uri: {audio_item['uri']}\n"
                    f"raw_audio_name: {audio_item.get('name', '')}\n"
                    f"raw_media_uris: {', '.join(media_uris)}"
                ),
            }
        ]
        manifest["message"] = message
        manifest["migrated_to_text"] = True
        self._write_manifest(manifest_path, manifest)

    def _schedule_retry(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._retry_task and not self._retry_task.done():
            return
        self._retry_task = loop.create_task(self._retry_pending_loop())

    async def _retry_pending_loop(self) -> None:
        for delay in (1, 5, 15, 30, 60):
            await asyncio.sleep(delay)
            await self.retry_pending_once()
        while True:
            await asyncio.sleep(60)
            await self.retry_pending_once()

    def _should_retry_manifest(self, manifest: dict) -> bool:
        last_attempt_ms = manifest.get("last_attempt_ms")
        if not last_attempt_ms:
            return True
        last_error = manifest.get("last_error") or {}
        backoff_ms = (
            TRANSCRIPTION_RETRY_BACKOFF_MS
            if last_error.get("type") == "TranscriptionUnavailableError"
            else DEFAULT_RETRY_BACKOFF_MS
        )
        return self._now_ms() - int(last_attempt_ms) >= backoff_ms

    @staticmethod
    def _serialize_error(exc: Exception) -> dict:
        payload = {
            "type": type(exc).__name__,
            "message": str(exc),
            "status_code": None,
            "path": None,
            "request_id": None,
        }
        if isinstance(exc, EverOSError):
            payload["status_code"] = exc.status_code
            payload["path"] = exc.path
            payload["request_id"] = exc.request_id
        return payload

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    async def _build_content(
        self,
        *,
        safe_session: str,
        wav_uri: str,
        wav_name: str,
        audio_chunks: list[StoredEvidence],
        prepared_images: list,
        sample_rate: int,
    ) -> list[dict]:
        evidence_ids = [
            evidence.evidence_id
            for evidence in sorted(audio_chunks, key=lambda item: item.path.name)
        ]
        if self.audio_transcriber is not None:
            pcm_bytes, wav_sample_rate = self._read_wav_uri(wav_uri)
            transcript = await self._transcribe_pcm_bytes(pcm_bytes, wav_sample_rate)
            if not transcript:
                raise TranscriptionUnavailableError(
                    f"ASR returned no usable text for session {safe_session}"
                )
            text = (
                f"Beaver Memory 记忆窗口 {safe_session}。\n"
                f"转写内容：\n{transcript}\n\n"
                f"raw_audio_uri: {wav_uri}\n"
                f"raw_audio_name: {wav_name}\n"
                f"raw_audio_chunk_count: {len(audio_chunks)}\n"
                f"raw_audio_evidence_ids: {', '.join(evidence_ids[:20])}"
                + (" ..." if len(evidence_ids) > 20 else "")
            )
            return [{"type": "text", "text": text}]

        return self._build_audio_content(
            wav_uri=wav_uri,
            wav_name=wav_name,
            audio_chunks=audio_chunks,
            prepared_images=prepared_images,
        )

    @staticmethod
    def _build_audio_content(
        *,
        wav_uri: str,
        wav_name: str,
        audio_chunks: list[StoredEvidence],
        prepared_images: list,
    ) -> list[dict]:
        evidence_ids = [
            evidence.evidence_id
            for evidence in sorted(audio_chunks, key=lambda item: item.path.name)
        ]
        return [
            {
                "type": "audio",
                "uri": wav_uri,
                "ext": "wav",
                "name": wav_name,
                "extras": {"evidence_ids": evidence_ids},
            },
            *[
                {
                    "type": "image",
                    "uri": image.uri,
                    "ext": "jpg",
                    "name": image.path.name,
                    "extras": {"captured_at_ms": image.captured_at_ms},
                }
                for image in prepared_images
            ],
        ]

    async def _transcribe_audio_chunks(
        self,
        audio_chunks: list[StoredEvidence],
        sample_rate: int,
    ) -> str:
        if self.audio_transcriber is None:
            return ""
        texts: list[str] = []
        group = bytearray()
        for evidence in sorted(audio_chunks, key=lambda item: item.path.name):
            body = evidence.path.read_bytes()
            if group and len(group) + len(body) > self.transcription_chunk_bytes:
                text = await self.audio_transcriber.transcribe(bytes(group), sample_rate)
                if text.strip():
                    texts.append(text.strip())
                group.clear()
            group.extend(body)
        if group:
            text = await self._transcribe_pcm_bytes(bytes(group), sample_rate)
            if text:
                texts.append(text)
        return "\n".join(texts).strip()

    async def _transcribe_pcm_bytes(self, pcm_bytes: bytes, sample_rate: int) -> str:
        if self.audio_transcriber is None:
            return ""
        texts: list[str] = []
        for offset in range(0, len(pcm_bytes), self.transcription_chunk_bytes):
            chunk = pcm_bytes[offset : offset + self.transcription_chunk_bytes]
            if not chunk:
                continue
            text = await self.audio_transcriber.transcribe(chunk, sample_rate)
            if text.strip():
                texts.append(text.strip())
        return "\n".join(texts).strip()

    @staticmethod
    def _read_wav_uri(uri: str) -> tuple[bytes, int]:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError(f"cannot transcribe non-file audio uri: {uri}")
        path = Path(parsed.path)
        with wave.open(str(path), "rb") as wav:
            sample_rate = wav.getframerate()
            pcm_bytes = wav.readframes(wav.getnframes())
        return pcm_bytes, sample_rate

    @staticmethod
    def _load_manifest(path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_manifest(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        try:
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _safe_part(value: str) -> str:
        if not value or not _SAFE_PART.fullmatch(value):
            raise ValueError(f"unsafe bridge path part: {value!r}")
        return value
