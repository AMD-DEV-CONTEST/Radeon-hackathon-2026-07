from __future__ import annotations

import base64
import asyncio
import json
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse, unquote

import httpx

from glass_gateway.config import Settings
from glass_gateway.providers.llm.qwen_options import (
    apply_qwen_request_options,
    post_chat_completion,
)


_INTERPRETATION_CONTRACT_VERSION = "first-person-caption-v1"
_ALLOWED_MODEL_FIELDS = {"first_person_caption"}
_EVENT_TYPES = {"daily", "object", "person", "meeting", "unknown"}  # legacy reader only
_LOGGER = logging.getLogger(__name__)


class OpenAICompatibleMemorySceneInterpreter:
    """Interprets one aligned glasses-memory window with an OpenAI-style API.

    The bridge keeps raw evidence and processing metadata locally. The model's
    only semantic output is a first-person caption for the current window.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        concurrency = max(
            1, int(getattr(settings, "memory_scene_max_concurrency", 1))
        )
        self._window_semaphore = asyncio.Semaphore(concurrency)
        self._provider_semaphore = asyncio.Semaphore(concurrency)

    async def interpret_window(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Serialize the complete degradation sequence, not only individual
        # HTTP calls. Otherwise newer windows can occupy the provider queue
        # before an older window gets its image-only fallback, and cards appear
        # increasingly late during continuous capture.
        async with self._window_semaphore:
            return await self._interpret_window_serialized(**kwargs)

    async def _interpret_window_serialized(
        self,
        *,
        window_id: str,
        captured_at_ms: int,
        duration_ms: int,
        wav_path: str,
        wav_uri: str,
        transcript: str,
        evidence: list[dict[str, Any]],
        images: list[dict[str, Any]],
        visible_people: list[dict[str, Any]],
        audio_speakers: list[dict[str, Any]],
        technical_window: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base_url = (self.settings.memory_scene_base_url or "").rstrip("/")
        api_key = self.settings.memory_scene_api_key
        model = self.settings.memory_scene_model
        if not base_url or not api_key or not model:
            return _failed_interpretation("provider_not_configured", transcript=transcript)

        attempts: list[dict[str, Any]] = []
        attempted_signatures: set[tuple[int, bool]] = set()
        provider_attempt_count = 0
        evidence_ids = [
            str(item.get("id"))
            for item in evidence
            if item.get("id")
        ]
        for attach_images, attach_audio in ((True, True), (True, False), (False, False)):
            content = self._build_content(
                window_id=window_id,
                captured_at_ms=captured_at_ms,
                duration_ms=duration_ms,
                wav_path=wav_path,
                transcript=transcript,
                evidence=evidence,
                images=images,
                visible_people=visible_people,
                audio_speakers=audio_speakers,
                technical_window=technical_window,
                attach_images=attach_images,
                attach_audio=attach_audio,
            )
            usage = _content_usage(content, transcript=transcript)
            signature = (usage["attached_image_count"], usage["attached_audio"])
            if signature in attempted_signatures:
                continue
            attempted_signatures.add(signature)
            attempts.append(usage)
            data: dict[str, Any] = {}
            # A timed-out all-modal request may continue consuming GPU on the
            # provider even after the client disconnects. Re-submitting the
            # same large payload amplifies queue pressure and cost, so each
            # degradation level gets exactly one attempt.
            provider_attempt_limit = 1
            for _ in range(provider_attempt_limit):
                provider_attempt_count += 1
                data = await self._complete_json(base_url, api_key, model, content)
                if data:
                    break
            if data:
                normalized = _normalize_interpretation(data)
                schema_errors = _interpretation_schema_errors(data, normalized=normalized)
                normalized.update(
                    {
                        "contract_version": _INTERPRETATION_CONTRACT_VERSION,
                        "status": "completed" if not schema_errors else "failed",
                        "contract_valid": not schema_errors,
                        "schema_errors": schema_errors,
                        "evidence_refs": evidence_ids,
                        "input_usage": {
                            "successful_level": usage["level"],
                            "attached_image_count": usage["attached_image_count"],
                            "attached_audio": usage["attached_audio"],
                            "asr_present": usage["asr_present"],
                            "fallback_used": len(attempts) > 1,
                            "attempted_levels": [item["level"] for item in attempts],
                            "provider_attempt_count": provider_attempt_count,
                            "provider_retry_used": provider_attempt_count > len(attempts),
                        },
                    }
                )
                return normalized
        failed = _failed_interpretation("all_provider_attempts_failed", transcript=transcript)
        failed["input_usage"]["attempted_levels"] = [item["level"] for item in attempts]
        failed["input_usage"]["fallback_used"] = len(attempts) > 1
        failed["input_usage"]["provider_attempt_count"] = provider_attempt_count
        failed["input_usage"]["provider_retry_used"] = provider_attempt_count > len(attempts)
        return failed

    def _build_content(
        self,
        *,
        window_id: str,
        captured_at_ms: int,
        duration_ms: int,
        wav_path: str,
        transcript: str,
        evidence: list[dict[str, Any]],
        images: list[dict[str, Any]],
        visible_people: list[dict[str, Any]],
        audio_speakers: list[dict[str, Any]],
        technical_window: dict[str, Any] | None,
        attach_images: bool,
        attach_audio: bool,
    ) -> list[dict[str, Any]]:
        prompt = {
            "task": "这是一段佩戴者第一视觉的视频，请你根据同一技术窗口内的原始音频、画面、ASR 和身份候选，描述佩戴者第一视角的当前经历。",
            "rules": [
                "只输出 first_person_caption 一个语义字段，不得输出 scene、activity、observations、visible_people、audio_speakers、objects、meeting、event_type、memory_value 或 uncertainties。",
                "佩戴眼镜的人始终写作“我”；caption 是我对当前片段的经历，不是系统日志、监控报告或第三人称摘要。",
                "只写当前窗口实际看到、听到以及结合证据合理推测的内容；不得凭空补全具体人物、地点、动作、金额或承诺。",
                "允许推测我在做什么，但不确定内容要自然使用“像是、可能、似乎”等措辞。",
                "多张图片按时间先后排列；先重建窗口内开始、变化和结果，再写成连贯经历，不要把各帧当成互不相关的静态照片罗列。",
                "ASR 可用于解释画面中不明显的活动；当对话反复提及某项行为（例如压花、找手套）且与画面不冲突时，应保留该事件主线。",
                "ASR 可能有同音词和跨语言误识别；具体名词与画面冲突时不要照抄，可改写成中性的‘一件物品’或使用不确定措辞。",
                "优先描述人物间的动作、我的参与和片段内发生的变化；背景陈设只在帮助理解事件时提及。",
                "优先保留能区分相邻窗口的新细节，避免反复输出泛化的“我在室内与人交流”。",
                "不要写“我记录到”“系统检测到”“画面显示”“证据不足”“等待模型处理”等元数据措辞。",
                "若我看着 Steven 而 James 在说话，应写成“我正看着 Steven；James 在说话”，不得把两人强行合并。",
                "ASR 只是辅助线索；必须结合完整原音中的音色、语气和环境声。",
                "audio_presence 只决定 ASR 是否运行，不代表非人声环境音没有记忆价值。",
                "身份候选只有达到输入所示的确定程度时才可使用姓名；候选不确定时使用自然的不确定措辞。",
                "不要罗列检测标签或生成物品卡片；YOLOE 属于另一条独立物品链路，本请求没有 YOLOE 输入。",
                "技术窗口结束不代表事件结束，不要写‘会议结束’‘离开了’等无证据边界。",
                "信息很少时宁可写简短、诚实的经历，也不要生成丰富故事。",
                "输出简洁但包含关键细节的中文 caption，最多 1200 个字符。",
            ],
            "window": {
                "window_id": window_id,
                "captured_at_ms": captured_at_ms,
                "duration_ms": duration_ms,
            },
            "transcript": transcript,
            "image_timeline": [
                {
                    "index": index,
                    "captured_at_ms": image.get("captured_at_ms"),
                    "offset_ms": (
                        int(image.get("captured_at_ms")) - captured_at_ms
                        if image.get("captured_at_ms") is not None
                        else None
                    ),
                }
                for index, image in enumerate(
                    images[: self.settings.memory_scene_max_images], start=1
                )
            ],
            "technical_window": _compact_technical_window(technical_window),
            "visible_people": _compact_people(visible_people),
            "audio_speakers": _compact_people(audio_speakers),
            "evidence": [
                {
                    "id": item.get("id"),
                    "kind": item.get("kind"),
                    "captured_at_ms": item.get("captured_at_ms"),
                }
                for item in evidence[:20]
            ],
            "required_json_schema": {
                "first_person_caption": "当前窗口的第一人称中文经历；直接观察用肯定句，推测用自然的不确定措辞",
            },
        }
        content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(prompt, ensure_ascii=False)}]

        if attach_images:
            for image in images[: self.settings.memory_scene_max_images]:
                data_url = _image_data_url(image.get("uri"))
                if data_url:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        }
                    )

        if attach_audio and self.settings.memory_scene_attach_audio:
            audio = _input_audio(
                wav_path,
                max_bytes=self.settings.memory_scene_max_audio_bytes,
                transport=getattr(
                    self.settings,
                    "memory_scene_audio_transport",
                    "input_audio",
                ),
            )
            if audio:
                content.append(audio)
        return content

    async def _complete_json(
        self,
        base_url: str,
        api_key: str,
        model: str,
        content: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = self._completion_payload(
            model=model,
            max_tokens=self.settings.memory_scene_max_tokens,
            content=content,
            base_url=base_url,
        )
        headers = self._headers(api_key)
        try:
            async with self._provider_semaphore:
                async with httpx.AsyncClient(
                    timeout=self.settings.memory_scene_timeout_seconds,
                    trust_env=False,
                ) as client:
                    body = await post_chat_completion(
                        client,
                        url=f"{base_url}/chat/completions",
                        headers=headers,
                        payload=payload,
                    )
        except Exception as exc:
            _LOGGER.warning(
                "memory scene provider request failed model=%s content_types=%s error=%s: %s",
                model,
                [item.get("type") for item in content],
                type(exc).__name__,
                str(exc)[:500],
            )
            return {}
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return {}
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        content_text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content_text, str):
            reasoning_content = message.get("reasoning_content") if isinstance(message, dict) else None
            if isinstance(reasoning_content, str):
                content_text = reasoning_content
            else:
                return {}
        return _parse_json_object(content_text)

    @staticmethod
    def _completion_payload(
        *,
        model: str,
        max_tokens: int,
        content: list[dict[str, Any]],
        base_url: str,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "只输出严格 JSON object，且唯一字段必须是 first_person_caption。不要输出 markdown、额外解释或其他字段。",
                },
                {"role": "user", "content": content},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        normalized_model = model.strip().lower()
        is_mimo = "mimo" in normalized_model.rsplit("/", 1)[-1]
        if "xiaomimimo.com" in base_url or is_mimo:
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
        if is_mimo and "xiaomimimo.com" not in base_url:
            # Local MiMo deployments are commonly served by vLLM. Their
            # guided JSON decoder currently aborts valid multimodal requests,
            # while the model's chat template otherwise spends the whole
            # completion budget in reasoning. Use the vLLM template switch and
            # retain strictness through the prompt plus local schema checking.
            payload.pop("response_format", None)
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return apply_qwen_request_options(payload, model=model)

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "api-key": api_key,
            "Content-Type": "application/json",
        }


def _compact_people(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for item in items[:10]:
        compact.append(
            {
                "name": item.get("name") or item.get("candidate_id"),
                "candidate_id": item.get("candidate_id"),
                "confidence": item.get("confidence"),
                "source": item.get("source"),
                "evidence_id": item.get("evidence_id"),
            }
        )
    return compact


def _compact_technical_window(value: dict[str, Any] | None) -> dict[str, Any]:
    """Keep model-useful signals without resending verbose processing records."""

    if not isinstance(value, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "duration_ms",
        "window_kind",
        "capture_state",
        "image_interval_ms",
    ):
        if value.get(key) is not None:
            compact[key] = value[key]

    presence = value.get("audio_presence")
    if isinstance(presence, dict):
        compact["audio_presence"] = {
            key: presence.get(key)
            for key in (
                "status",
                "presence_class",
                "speech_present",
                "speech_probability",
                "music_probability",
                "speech_coverage",
                "non_speech_activity",
                "audio_level_dbfs",
                "warnings",
                "error",
            )
            if presence.get(key) is not None
        }

    return compact


def _image_data_url(uri: Any) -> str | None:
    path = _file_uri_to_path(uri)
    if path is None or not path.is_file():
        return None
    suffix = path.suffix.lower()
    media_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png" if suffix == ".png" else None
    if media_type is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def _input_audio(
    wav_path: str,
    *,
    max_bytes: int,
    transport: str = "input_audio",
) -> dict[str, Any] | None:
    path = Path(wav_path)
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > max_bytes:
        return None
    data_url = f"data:audio/wav;base64,{base64.b64encode(data).decode('ascii')}"
    if transport.strip().lower() == "audio_url":
        # vLLM's all-modal Chat Completions schema uses the same URL-style
        # content contract for audio as it does for images and videos.
        return {"type": "audio_url", "audio_url": {"url": data_url}}
    return {
        "type": "input_audio",
        "input_audio": {"data": data_url},
    }


def _file_uri_to_path(uri: Any) -> Path | None:
    if not isinstance(uri, str) or not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if parsed.scheme == "":
        return Path(uri)
    return None


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    # Some reasoning models return an internal thinking block followed by the
    # requested JSON.  Parsing from the first ``{`` greedily can accidentally
    # turn the end of that block into the caption (for example ``}</think>{``).
    if "</think>" in cleaned:
        cleaned = cleaned.rsplit("</think>", 1)[-1].strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        candidates: list[dict[str, Any]] = []
        for index, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                candidates.append(value)
        if not candidates:
            # Some local MiMo/vLLM combinations follow the one-field contract
            # but omit the opening quote around the caption value. Recover
            # only that explicitly allowed field; schema validation still
            # rejects any additional semantic fields.
            match = re.search(
                r'["\']?first_person_caption["\']?\s*:\s*(.+)',
                cleaned,
                flags=re.DOTALL,
            )
            if not match:
                return {}
            caption = re.sub(r"\s*```.*$", "", match.group(1), flags=re.DOTALL)
            caption = caption.strip()
            if caption.endswith("}"):
                caption = caption[:-1].rstrip()
            if caption.startswith(('"', "'")):
                caption = caption[1:]
            if caption.endswith(('"', "'")):
                caption = caption[:-1]
            caption = caption.strip()
            return {"first_person_caption": caption} if caption else {}
        data = next(
            (
                value
                for value in reversed(candidates)
                if isinstance(value.get("first_person_caption"), str)
            ),
            candidates[-1],
        )
    return data if isinstance(data, dict) else {}


def _normalize_interpretation(
    data: dict[str, Any], *, evidence_ids: set[str] | None = None
) -> dict[str, Any]:
    """Normalize the caption-only semantic contract.

    ``evidence_ids`` remains in the signature for old callers. Evidence is
    bridge metadata and is deliberately not accepted from model output.
    """

    del evidence_ids
    if not isinstance(data, dict):
        return {}
    caption = data.get("first_person_caption")
    if not isinstance(caption, str) or not caption.strip():
        return {}
    return {"first_person_caption": caption.strip()[:1200]}


def _normalize_legacy_interpretation(
    data: dict[str, Any], *, evidence_ids: set[str] | None = None
) -> dict[str, Any]:
    """Read-only compatibility parser for pre-caption-only stored records."""

    if not isinstance(data, dict):
        return {}
    evidence_ids = evidence_ids or set()
    result: dict[str, Any] = {}
    for key in ("scene", "activity"):
        claim = _normalize_claim(data.get(key), evidence_ids=evidence_ids)
        if claim:
            result[key] = claim
    caption = data.get("first_person_caption")
    if isinstance(caption, str) and caption.strip():
        result["first_person_caption"] = caption.strip()[:1200]

    observations = []
    for item in data.get("observations") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        observations.append(
            {
                "text": text[:500],
                "evidence_refs": _normalize_evidence_refs(
                    item.get("evidence_refs"), evidence_ids=evidence_ids
                ),
            }
        )
    result["observations"] = observations[:20]

    uncertainties = []
    for item in data.get("uncertainties") or []:
        text = str(item or "").strip()
        if text:
            uncertainties.append(text[:300])
    result["uncertainties"] = uncertainties[:10]
    result["visible_people"] = _normalize_people_projection(
        data.get("visible_people"), evidence_ids=evidence_ids
    )
    result["audio_speakers"] = _normalize_people_projection(
        data.get("audio_speakers"), evidence_ids=evidence_ids
    )

    event_type = data.get("event_type")
    if isinstance(event_type, str) and event_type in _EVENT_TYPES:
        result["event_type"] = event_type
    likelihood = data.get("meeting_likelihood")
    if isinstance(likelihood, (int, float)):
        result["meeting_likelihood"] = max(0.0, min(1.0, float(likelihood)))

    objects = []
    raw_objects = data.get("objects")
    if isinstance(raw_objects, list):
        for item in raw_objects[:10]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("object_label") or "").strip()
            if not label:
                continue
            confidence = item.get("confidence")
            if not isinstance(confidence, (int, float)):
                confidence = 0.5
            semantic_confidence = item.get("semantic_confidence")
            if not isinstance(semantic_confidence, (int, float)):
                semantic_confidence = confidence
            memory_value = str(item.get("memory_value") or "context_only")
            if memory_value not in {"memory_critical", "context_only", "ignore"}:
                memory_value = "context_only"
            evidence_refs = _normalize_evidence_refs(
                item.get("evidence_refs"), evidence_ids=evidence_ids
            )
            # Hearing an object mentioned can help scene context, but cannot
            # establish a reliable "last seen" location without visual proof.
            if memory_value == "memory_critical" and not any(
                ref.startswith(("img_", "img-")) for ref in evidence_refs
            ):
                memory_value = "context_only"
            evidence_id = str(item.get("evidence_id") or "").strip()
            if evidence_id not in evidence_ids:
                evidence_id = evidence_refs[0] if evidence_refs else ""
            elif evidence_id not in evidence_refs:
                evidence_refs.insert(0, evidence_id)
            objects.append(
                {
                    "label": label[:80],
                    "normalized_label": str(item.get("normalized_label") or "").strip()[:80]
                    or None,
                    "personal_object_id": str(item.get("personal_object_id") or "").strip()[:160]
                    or None,
                    "visible_description": str(item.get("visible_description") or "").strip()[:300]
                    or None,
                    "relation": str(item.get("relation") or "unknown").strip()[:80],
                    "confidence": max(0.0, min(1.0, float(confidence))),
                    "semantic_confidence": max(
                        0.0, min(1.0, float(semantic_confidence))
                    ),
                    "location_hint": str(item.get("location_hint") or item.get("location") or "").strip()[:160],
                    "memory_value": memory_value,
                    "instance_ambiguity": bool(item.get("instance_ambiguity", False)),
                    "evidence_id": evidence_id,
                    "evidence_refs": evidence_refs,
                    "image_uri": str(item.get("image_uri") or item.get("uri") or "").strip(),
                }
            )
    # Keep the projection shape stable: no relevant object is a valid empty
    # result, not a missing/failed object stage.
    result["objects"] = objects

    meeting = data.get("meeting")
    if isinstance(meeting, dict):
        summary = str(meeting.get("summary") or "").strip()
        commitments = []
        for item in meeting.get("commitments") or []:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            commitments.append(
                {
                    "owner": str(item.get("owner") or "未知").strip()[:80],
                    "text": str(item.get("text") or "").strip()[:300],
                    "due_hint": str(item.get("due_hint") or "").strip()[:80] or None,
                    "status": str(item.get("status") or "open").strip()[:40],
                }
            )
        normalized_meeting = {
            "summary": summary[:800],
            "commitments": commitments[:10],
            "transcript_excerpt": str(meeting.get("transcript_excerpt") or "").strip()[:1500],
        }
        if normalized_meeting["summary"] or normalized_meeting["commitments"]:
            result["meeting"] = normalized_meeting
    return result


def _normalize_claim(value: Any, *, evidence_ids: set[str]) -> dict[str, Any] | None:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return {"value": text[:500], "confidence": 0.5, "evidence_refs": []}
    if not isinstance(value, dict):
        return None
    text = str(value.get("value") or value.get("text") or "").strip()
    if not text:
        return None
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    return {
        "value": text[:500],
        "confidence": max(0.0, min(1.0, float(confidence))),
        "evidence_refs": _normalize_evidence_refs(
            value.get("evidence_refs"), evidence_ids=evidence_ids
        ),
    }


def _normalize_people_projection(value: Any, *, evidence_ids: set[str]) -> list[dict[str, Any]]:
    people = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("candidate_id") or "").strip()
        if not name:
            continue
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0.5
        people.append(
            {
                "name": name[:100],
                "candidate_id": str(item.get("candidate_id") or "").strip()[:100] or None,
                "confidence": max(0.0, min(1.0, float(confidence))),
                "evidence_refs": _normalize_evidence_refs(
                    item.get("evidence_refs") or [item.get("evidence_id")],
                    evidence_ids=evidence_ids,
                ),
            }
        )
    return people[:10]


def _normalize_evidence_refs(value: Any, *, evidence_ids: set[str]) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return list(
        dict.fromkeys(
            str(item).strip()
            for item in values
            if str(item or "").strip() in evidence_ids
        )
    )[:10]


def _interpretation_schema_errors(
    raw: dict[str, Any], *, normalized: dict[str, Any] | None = None
) -> list[str]:
    if not isinstance(raw, dict):
        return ["model_output_not_object"]
    errors: list[str] = []
    unexpected = sorted(str(key) for key in raw if key not in _ALLOWED_MODEL_FIELDS)
    if unexpected:
        errors.append("unexpected_semantic_fields:" + ",".join(unexpected))
    normalized = normalized if normalized is not None else _normalize_interpretation(raw)
    caption = normalized.get("first_person_caption")
    if not isinstance(caption, str) or not caption.strip():
        errors.append("first_person_caption_required")
    return errors


def _content_usage(content: list[dict[str, Any]], *, transcript: str) -> dict[str, Any]:
    image_count = sum(item.get("type") == "image_url" for item in content)
    attached_audio = any(
        item.get("type") in {"input_audio", "audio_url"} for item in content
    )
    asr_present = bool(transcript.strip())
    if image_count and attached_audio:
        level = "full_multimodal"
    elif image_count and asr_present:
        level = "image_asr"
    elif image_count:
        level = "image_only"
    elif attached_audio and asr_present:
        level = "audio_asr"
    elif attached_audio:
        level = "audio_only"
    elif asr_present:
        level = "asr_only"
    else:
        level = "metadata_only"
    return {
        "level": level,
        "attached_image_count": image_count,
        "attached_audio": attached_audio,
        "asr_present": asr_present,
    }


def _failed_interpretation(reason: str, *, transcript: str) -> dict[str, Any]:
    return {
        "contract_version": _INTERPRETATION_CONTRACT_VERSION,
        "status": "failed",
        "contract_valid": False,
        "schema_errors": ["interpretation_failed"],
        "evidence_refs": [],
        "input_usage": {
            "successful_level": "failed",
            "attached_image_count": 0,
            "attached_audio": False,
            "asr_present": bool(transcript.strip()),
            "fallback_used": False,
            "attempted_levels": [],
            "failure_reason": reason,
        },
    }
