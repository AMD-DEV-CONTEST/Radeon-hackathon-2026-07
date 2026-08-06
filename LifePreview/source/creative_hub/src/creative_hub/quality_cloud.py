from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from functools import lru_cache
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Protocol

from shared_contracts import AtomicArtifactRef, OperationRequest

from .quality import QCEvaluatorResult
from .quality_atomic import (
    QualityEvaluatorOutputInvalid,
    QualityEvaluatorUnavailable,
)


QWEN_QUALITY_MODEL = "qwen3.7-plus"
QWEN_QUALITY_HOST = "token-plan.cn-beijing.maas.aliyuncs.com"
QWEN_QUALITY_PATH = "/compatible-mode/v1/chat/completions"
_MAX_MEDIA_BYTES = 2 * 1024**3
_MAX_RESPONSE_BYTES = 2 * 1024**2
_MAX_FRAMES = 12


class QualityArtifactReader(Protocol):
    def read_bytes(self, artifact: AtomicArtifactRef, /) -> bytes: ...


class QwenQualityTransport:
    def __call__(
        self,
        payload: Mapping[str, object],
        api_key: str,
    ) -> Mapping[str, object]:
        body = json.dumps(
            dict(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        connection = http.client.HTTPSConnection(
            QWEN_QUALITY_HOST,
            443,
            timeout=180,
        )
        try:
            connection.request(
                "POST",
                QWEN_QUALITY_PATH,
                body=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (OSError, TimeoutError, http.client.HTTPException):
            raise QualityEvaluatorUnavailable(
                "machine quality provider is unavailable"
            ) from None
        finally:
            connection.close()
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise QualityEvaluatorUnavailable(
                "machine quality response is too large"
            )
        if response.status in {401, 403, 408, 409, 429} or (
            response.status >= 500
        ):
            raise QualityEvaluatorUnavailable(
                "machine quality provider rejected the request"
            )
        if not 200 <= response.status < 300:
            raise QualityEvaluatorOutputInvalid(
                "machine quality request is invalid"
            )
        try:
            parsed = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            raise QualityEvaluatorUnavailable(
                "machine quality response is invalid"
            ) from None
        if not isinstance(parsed, Mapping):
            raise QualityEvaluatorUnavailable(
                "machine quality response is invalid"
            )
        return parsed


def _credential(
    provider: Callable[[str, str], str],
) -> str:
    try:
        value = provider("qwen", QWEN_QUALITY_MODEL)
    except Exception:
        raise QualityEvaluatorUnavailable(
            "machine quality credentials are unavailable"
        ) from None
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 4096
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        raise QualityEvaluatorUnavailable(
            "machine quality credentials are invalid"
        )
    return value


def _jpeg_data_url(image: Any) -> str:
    try:
        import cv2

        encoded, payload = cv2.imencode(
            ".jpg",
            image,
            [cv2.IMWRITE_JPEG_QUALITY, 82],
        )
    except Exception:
        raise QualityEvaluatorUnavailable(
            "machine quality frame encoding failed"
        ) from None
    if not encoded:
        raise QualityEvaluatorUnavailable(
            "machine quality frame encoding failed"
        )
    return (
        "data:image/jpeg;base64,"
        + base64.b64encode(payload.tobytes()).decode("ascii")
    )


def _image_frame(payload: bytes) -> tuple[tuple[float, str], ...]:
    try:
        import cv2
        import numpy

        image = cv2.imdecode(
            numpy.frombuffer(payload, dtype=numpy.uint8),
            cv2.IMREAD_COLOR,
        )
    except Exception:
        image = None
    if image is None or image.size == 0:
        raise QualityEvaluatorUnavailable(
            "machine quality image evidence is invalid"
        )
    return ((0.0, _jpeg_data_url(image)),)


def _video_frames(path: Path) -> tuple[tuple[float, str], ...]:
    try:
        import cv2

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise QualityEvaluatorUnavailable(
                "machine quality video evidence is invalid"
            )
        total = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        fps = fps if fps > 0 else 25.0
        count = min(_MAX_FRAMES, total)
        indices = tuple(
            round(index * (total - 1) / max(1, count - 1))
            for index in range(count)
        )
        frames: list[tuple[float, str]] = []
        for index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if ok and frame is not None and frame.size:
                frames.append((index / fps, _jpeg_data_url(frame)))
        capture.release()
    except QualityEvaluatorUnavailable:
        raise
    except Exception:
        raise QualityEvaluatorUnavailable(
            "machine quality video frame extraction failed"
        ) from None
    if not frames:
        raise QualityEvaluatorUnavailable(
            "machine quality video contains no decodable frames"
        )
    return tuple(frames)


def _has_audio(path: Path) -> bool:
    try:
        result = subprocess.run(
            (
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ),
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        raise QualityEvaluatorUnavailable(
            "machine quality audio probe failed"
        ) from None
    return result.returncode == 0 and bool(result.stdout.strip())


def _extract_audio(path: Path, output: Path) -> bool:
    if not _has_audio(path):
        return False
    try:
        result = subprocess.run(
            (
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(output),
            ),
            check=False,
            capture_output=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        raise QualityEvaluatorUnavailable(
            "machine quality audio extraction failed"
        ) from None
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise QualityEvaluatorUnavailable(
            "machine quality audio extraction failed"
        )
    return True


@lru_cache(maxsize=1)
def _cpu_whisper(model_snapshot: str):
    try:
        from faster_whisper import WhisperModel

        return WhisperModel(
            model_snapshot,
            device="cpu",
            compute_type="int8",
            local_files_only=True,
        )
    except Exception:
        raise QualityEvaluatorUnavailable(
            "machine quality speech model is unavailable"
        ) from None


def _default_transcript(audio_path: Path, model_root: Path) -> str:
    try:
        from douyin_analysis.semantic_adapters import model_snapshot_paths

        snapshot = model_snapshot_paths(model_root)[0]
        if not snapshot.is_dir():
            raise QualityEvaluatorUnavailable(
                "machine quality speech model is unavailable"
            )
        segments, _info = _cpu_whisper(str(snapshot)).transcribe(
            str(audio_path),
            beam_size=3,
            vad_filter=True,
            word_timestamps=False,
        )
        values = [
            f"[{float(segment.start):.3f}-{float(segment.end):.3f}] "
            f"{str(segment.text).strip()}"
            for segment in segments
            if str(segment.text).strip()
        ]
    except QualityEvaluatorUnavailable:
        raise
    except Exception:
        raise QualityEvaluatorUnavailable(
            "machine quality speech analysis failed"
        ) from None
    return "\n".join(values) or "[NO_SPEECH_DETECTED]"


def _result_text(response: Mapping[str, object]) -> str:
    try:
        choices = response["choices"]
        choice = choices[0]  # type: ignore[index]
        if choice.get("finish_reason") == "content_filter":
            raise QualityEvaluatorUnavailable(
                "machine quality content policy rejected the evidence"
            )
        value = choice["message"]["content"]
    except QualityEvaluatorUnavailable:
        raise
    except (KeyError, IndexError, TypeError, AttributeError):
        raise QualityEvaluatorUnavailable(
            "machine quality response is invalid"
        ) from None
    if not isinstance(value, str) or not value.strip():
        raise QualityEvaluatorUnavailable(
            "machine quality response is empty"
        )
    return value.strip()


def _parse_result(value: str) -> QCEvaluatorResult:
    if not value.startswith("{") or not value.endswith("}"):
        raise QualityEvaluatorOutputInvalid(
            "machine quality output is not one JSON object"
        )
    try:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError
        estimated_usage = parsed.get("estimated_usage")
        if estimated_usage is not None:
            if (
                "generation_usage" in parsed
                or not isinstance(estimated_usage, dict)
                or set(estimated_usage) != {"generation_usage"}
                or not isinstance(
                    estimated_usage.get("generation_usage"),
                    dict,
                )
            ):
                raise ValueError
            parsed = dict(parsed)
            parsed["generation_usage"] = estimated_usage["generation_usage"]
            del parsed["estimated_usage"]
        defects = parsed.get("defects")
        if isinstance(defects, list):
            severity_aliases = {
                "LOW": "MINOR",
                "MEDIUM": "MAJOR",
                "HIGH": "CRITICAL",
            }
            normalized_defects = []
            for defect in defects:
                severity = (
                    defect.get("severity")
                    if isinstance(defect, dict)
                    else None
                )
                if isinstance(severity, str) and severity in severity_aliases:
                    defect = dict(defect)
                    defect["severity"] = severity_aliases[severity]
                normalized_defects.append(defect)
            parsed = dict(parsed)
            parsed["defects"] = normalized_defects
        return QCEvaluatorResult.model_validate(parsed)
    except Exception:
        raise QualityEvaluatorOutputInvalid(
            "machine quality output failed the frozen result contract"
        ) from None


class QwenFrameAudioQualityBackend:
    """Real Qwen evaluator over bounded frame samples and local ASR evidence."""

    def __init__(
        self,
        *,
        artifacts: QualityArtifactReader,
        credential_provider: Callable[[str, str], str],
        model_root: Path,
        transport: (
            Callable[
                [Mapping[str, object], str],
                Mapping[str, object],
            ]
            | None
        ) = None,
        transcriber: Callable[[Path, Path], str] | None = None,
    ) -> None:
        self.artifacts = artifacts
        self.credential_provider = credential_provider
        self.model_root = model_root
        self.transport = transport or QwenQualityTransport()
        self.transcriber = transcriber or _default_transcript

    def evaluate(self, request: OperationRequest, /) -> QCEvaluatorResult:
        if len(request.input_artifact_refs) != 1:
            raise QualityEvaluatorOutputInvalid(
                "machine quality requires exactly one candidate artifact"
            )
        artifact = request.input_artifact_refs[0]
        if artifact.byte_size > _MAX_MEDIA_BYTES:
            raise QualityEvaluatorOutputInvalid(
                "machine quality candidate exceeds the media budget"
            )
        try:
            payload = self.artifacts.read_bytes(artifact)
        except Exception:
            raise QualityEvaluatorUnavailable(
                "machine quality candidate is unavailable"
            ) from None
        if (
            len(payload) != artifact.byte_size
            or hashlib.sha256(payload).hexdigest()
            != artifact.content_digest
        ):
            raise QualityEvaluatorOutputInvalid(
                "machine quality candidate integrity mismatch"
            )
        transcript = "[NOT_APPLICABLE]"
        with tempfile.TemporaryDirectory(
            prefix="creative-hub-quality-"
        ) as raw:
            workspace = Path(raw)
            if artifact.mime_type.startswith("image/"):
                frames = _image_frame(payload)
            elif artifact.mime_type.startswith("video/"):
                video = workspace / "candidate.mp4"
                video.write_bytes(payload)
                frames = _video_frames(video)
                audio = workspace / "candidate.wav"
                transcript = (
                    self.transcriber(audio, self.model_root)
                    if _extract_audio(video, audio)
                    else "[NO_AUDIO_TRACK]"
                )
            else:
                raise QualityEvaluatorOutputInvalid(
                    "machine quality candidate MIME type is unsupported"
                )
        stage = str(request.structured_inputs.get("quality_stage") or "")
        gate_key = str(request.structured_inputs.get("gate_key") or "")
        responsible_node = str(
            request.structured_inputs.get("responsible_node_id") or gate_key
        )
        prompt_text = str(
            request.structured_inputs.get("prompt_text")
            or "按镜头可用性、画面一致性、运动稳定性、音画质量评分。"
        )
        instruction = (
            "你是短剧出厂质检模型。只返回一个 JSON 对象，禁止 Markdown。"
            "必须严格符合 QCEvaluatorResult：judgment 为 PASS 或 FAIL；"
            "quality_score 为 0-100；confidence 为 0-1；defects 为数组。"
            "每个 defect 必须包含 defect_code、severity、message、"
            "time_range_ms、subject_refs、evidence_refs、"
            "responsible_node_ids、recommended_repair_action。"
            "severity 只能是 MINOR、MAJOR 或 CRITICAL。"
            "除冻结枚举、defect_code、subject_refs、evidence_refs 和责任节点 ID 外，"
            "所有面向用户的自然语言字段必须使用简体中文，包括 message、"
            "recommended_repair_action、recommended_actions 以及 changed_parameters 中的文字说明。"
            "PASS 时 defects 为空且 repair_result.disposition=NOT_REQUIRED；"
            "FAIL 时至少一个 defect，repair_result.disposition=PLANNED，"
            "并提供 repair_directive.changed_parameters 和 estimated_usage。"
            "generation_usage 必须包含 cost_micros、gpu_seconds、wall_seconds。"
            "禁止在顶层输出 estimated_usage 或任何未列出的字段；"
            "repair_directive 内仍必须使用 estimated_usage。"
            "PASS 的精确结构示例："
            '{"judgment":"PASS","quality_score":95,'
            '"confidence":0.98,"defects":[],"recommended_actions":[],'
            '"repair_result":{"disposition":"NOT_REQUIRED"},'
            '"repair_directive":null,"generation_usage":'
            '{"cost_micros":0,"gpu_seconds":0,"wall_seconds":0}}。'
            f"\n质量阶段：{stage}\n质量门：{gate_key}"
            f"\n责任节点：{responsible_node}\n冻结评价提示：{prompt_text}"
            f"\n时间戳转写：\n{transcript[:20_000]}"
        )
        content: list[dict[str, object]] = [
            {"type": "text", "text": instruction}
        ]
        for index, (seconds, image_url) in enumerate(frames, start=1):
            content.extend(
                (
                    {
                        "type": "text",
                        "text": f"Frame {index:02d} at {seconds:.3f}s",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                )
            )
        try:
            response = self.transport(
                {
                    "model": QWEN_QUALITY_MODEL,
                    "messages": [{"role": "user", "content": content}],
                    "enable_thinking": False,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
                _credential(self.credential_provider),
            )
        except (
            QualityEvaluatorOutputInvalid,
            QualityEvaluatorUnavailable,
        ):
            raise
        except Exception:
            raise QualityEvaluatorUnavailable(
                "machine quality provider is unavailable"
            ) from None
        return _parse_result(_result_text(response))


def build_qwen_quality_backend(
    *,
    request: OperationRequest,
    artifact_gateway: QualityArtifactReader,
    credential_resolver: Callable[[str, str], str] | None,
) -> QwenFrameAudioQualityBackend:
    del request
    if credential_resolver is None:
        raise QualityEvaluatorUnavailable(
            "machine quality credentials are unavailable"
        )
    try:
        from douyin_analysis.semantic_adapters import (
            run_semantic_preflight,
        )

        model_root = run_semantic_preflight(
            Path(
                os.environ.get(
                    "ANALYSIS_MODEL_ROOT",
                    "/runtime/models",
                )
            )
        )
    except Exception:
        raise QualityEvaluatorUnavailable(
            "machine quality speech model is unavailable"
        ) from None
    return QwenFrameAudioQualityBackend(
        artifacts=artifact_gateway,
        credential_provider=credential_resolver,
        model_root=model_root,
    )


__all__ = [
    "QWEN_QUALITY_MODEL",
    "QwenFrameAudioQualityBackend",
    "QwenQualityTransport",
    "QualityArtifactReader",
    "build_qwen_quality_backend",
]
