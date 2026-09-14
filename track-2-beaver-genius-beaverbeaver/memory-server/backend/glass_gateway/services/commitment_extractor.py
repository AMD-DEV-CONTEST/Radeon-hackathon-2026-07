from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from glass_gateway.services.memory_review_store import MemoryReviewStore
from glass_gateway.providers.llm.qwen_options import apply_qwen_request_options


CONTRACT_VERSION = "commitment-extraction-v1"
_SOFT_INTENTION_MARKERS = (
    "可能",
    "考虑",
    "希望",
    "有空",
    "方便的时候",
    "以后再",
    "可以看看",
    "应该",
    "建议",
    "不一定",
    "再说",
)
_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _compact_text(value: Any) -> str:
    return "".join(str(value or "").split()).strip()


def _end_of_day(value: datetime) -> datetime:
    return value.replace(hour=23, minute=59, second=59, microsecond=0)


def normalize_due_hint(
    due_hint: str | None,
    captured_at_ms: int,
    *,
    timezone_name: str = "Asia/Shanghai",
) -> str | None:
    """Resolve only explicit calendar hints; vague language stays unresolved."""

    hint = _compact_text(due_hint)
    if not hint:
        return None
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    captured = datetime.fromtimestamp(captured_at_ms / 1000, tz=tz)
    date_match = re.search(
        r"(?P<year>20\d{2})[-年/](?P<month>\d{1,2})[-月/](?P<day>\d{1,2})日?",
        hint,
    )
    target: datetime | None = None
    if date_match:
        try:
            target = datetime(
                int(date_match.group("year")),
                int(date_match.group("month")),
                int(date_match.group("day")),
                tzinfo=tz,
            )
        except ValueError:
            return None
    elif "后天" in hint:
        target = captured + timedelta(days=2)
    elif "明天" in hint:
        target = captured + timedelta(days=1)
    elif "今天" in hint:
        target = captured
    else:
        weekday = re.search(r"(?:本|这|下)?周([一二三四五六日天])", hint)
        if weekday:
            desired = _WEEKDAYS[weekday.group(1)]
            days = (desired - captured.weekday()) % 7
            if hint.startswith("下周"):
                days = days + 7 if days else 7
            target = captured + timedelta(days=days)
    if target is None:
        return None

    time_match = re.search(r"(?P<hour>\d{1,2})(?::|点)(?P<minute>\d{1,2})?", hint)
    if time_match:
        hour = int(time_match.group("hour"))
        minute = int(time_match.group("minute") or 0)
        if "下午" in hint and 1 <= hour < 12:
            hour += 12
        if hour > 23 or minute > 59:
            return None
        target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        target = _end_of_day(target)
    return target.isoformat()


def commitment_due_bucket(
    normalized_due_at: str | None,
    *,
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> str:
    """Map a confirmed due timestamp to the stable Web projection buckets."""

    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    current = now.astimezone(tz) if now is not None else datetime.now(tz)
    value = str(normalized_due_at or "").strip()
    if not value:
        return "no_due"
    try:
        due = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "no_due"
    if due.tzinfo is None:
        due = due.replace(tzinfo=tz)
    else:
        due = due.astimezone(tz)
    if due < current:
        return "overdue"
    if due.date() == current.date():
        return "today"
    if due <= current + timedelta(days=7):
        return "upcoming"
    return "later"


def _speaker_index(audio_speakers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in audio_speakers:
        if not isinstance(item, dict):
            continue
        for value in (
            item.get("person_id"),
            item.get("candidate_id"),
            item.get("speaker_id"),
            item.get("name"),
            item.get("label"),
        ):
            key = str(value or "").strip().casefold()
            if key:
                output[key] = item
    return output


def normalize_commitment_candidates(
    raw: dict[str, Any],
    *,
    transcript: str,
    audio_speakers: list[dict[str, Any]],
    captured_at_ms: int,
    evidence_refs: list[str],
    window_id: str,
    capsule_id: str,
    meeting_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    refs = list(dict.fromkeys(str(value).strip() for value in evidence_refs if str(value).strip()))
    if not refs:
        return [], ["evidence_refs_missing"]
    speakers = _speaker_index(audio_speakers)
    compact_transcript = _compact_text(transcript)
    values = raw.get("commitments") if isinstance(raw, dict) else None
    if not isinstance(values, list):
        return [], ["commitments_not_array"]
    for value in values[:20]:
        if not isinstance(value, dict):
            errors.append("commitment_not_object")
            continue
        text = " ".join(str(value.get("text") or "").split()).strip()
        quote = " ".join(str(value.get("source_quote") or "").split()).strip()
        if not text or not quote:
            errors.append("text_or_quote_missing")
            continue
        if str(value.get("commitment_strength") or "") != "explicit":
            errors.append("not_explicit")
            continue
        if any(marker in quote for marker in _SOFT_INTENTION_MARKERS):
            errors.append("soft_intention")
            continue
        if _compact_text(quote) not in compact_transcript:
            errors.append("source_quote_not_in_transcript")
            continue
        confidence = value.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        if float(confidence) < 0.65:
            errors.append("confidence_below_threshold")
            continue

        person_key = str(value.get("owner_person_id") or "").strip().casefold()
        candidate_key = str(value.get("owner_candidate_id") or "").strip().casefold()
        display_key = str(value.get("owner_display") or "").strip().casefold()
        speaker = speakers.get(person_key) or speakers.get(candidate_key) or speakers.get(display_key)
        if speaker is None:
            owner_person_id = None
            owner_candidate_id = None
            owner_display = "未知说话人"
        else:
            requested_person = str(value.get("owner_person_id") or "").strip()
            requested_candidate = str(value.get("owner_candidate_id") or "").strip()
            available_person = str(speaker.get("person_id") or "").strip()
            available_candidate = str(
                speaker.get("candidate_id") or speaker.get("speaker_id") or ""
            ).strip()
            owner_person_id = (
                requested_person
                if requested_person and requested_person == available_person
                else available_person or None
            )
            owner_candidate_id = (
                requested_candidate
                if requested_candidate and requested_candidate == available_candidate
                else available_candidate or None
            )
            owner_display = str(
                speaker.get("name") or speaker.get("label") or "未知说话人"
            ).strip()[:120]

        due_hint = str(value.get("due_hint") or "").strip()[:160] or None
        rows.append(
            {
                "owner_person_id": owner_person_id,
                "owner_candidate_id": owner_candidate_id,
                "owner_display": owner_display,
                "text": text[:800],
                "due_hint": due_hint,
                "normalized_due_at": normalize_due_hint(due_hint, captured_at_ms),
                "status": "candidate",
                "source_quote": quote[:1200],
                "evidence_refs": refs,
                "meeting_id": meeting_id,
                "capsule_id": capsule_id,
                "source_window_ids": [window_id],
                "confidence": max(0.0, min(1.0, float(confidence))),
                "contract_version": CONTRACT_VERSION,
            }
        )
    return rows, list(dict.fromkeys(errors))


class CommitmentExtractor:
    """Independent text-only commitment pass over ASR and speaker candidates."""

    def __init__(
        self,
        settings: Any,
        store: MemoryReviewStore,
        *,
        complete_json: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self._complete_json_override = complete_json

    async def process_window(
        self,
        *,
        window_id: str,
        capsule_id: str,
        captured_at_ms: int,
        transcript: str,
        audio_speakers: list[dict[str, Any]],
        evidence_refs: list[str],
        meeting_id: str | None = None,
    ) -> dict[str, Any]:
        if not str(transcript or "").strip():
            return self._result("no_transcript")
        if not evidence_refs:
            return self._result("evidence_missing", errors=["evidence_refs_missing"])
        if not bool(getattr(self.settings, "commitment_extraction_enabled", True)):
            return self._result("disabled")
        prompt = self._prompt(
            window_id=window_id,
            captured_at_ms=captured_at_ms,
            transcript=transcript,
            audio_speakers=audio_speakers,
            evidence_refs=evidence_refs,
        )
        try:
            raw = (
                await self._complete_json_override(prompt)
                if self._complete_json_override is not None
                else await self._complete_json(prompt)
            )
        except Exception as exc:
            return self._result("failed", errors=[f"{type(exc).__name__}: {exc}"])
        rows, errors = normalize_commitment_candidates(
            raw,
            transcript=transcript,
            audio_speakers=audio_speakers,
            captured_at_ms=captured_at_ms,
            evidence_refs=evidence_refs,
            window_id=window_id,
            capsule_id=capsule_id,
            meeting_id=meeting_id,
        )
        persisted = []
        model = str(getattr(self.settings, "commitment_extraction_model", "unknown"))
        for row in rows:
            persisted.append(
                self.store.upsert_commitment_candidate(
                    {**row, "source_model": model}
                )
            )
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "completed",
            "candidate_count": len(persisted),
            "candidates": persisted,
            "schema_errors": errors,
        }

    def _prompt(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "task": "从当前 ASR 片段中抽取明确由某人承担的未来行动，只生成待用户确认的承诺候选。",
            "rules": [
                "只提取明确承担行动的句子；可能、考虑、希望、建议、应该、有空看看不是承诺。",
                "source_quote 必须逐字来自 transcript，保留足以核对的完整原话。",
                "owner_person_id 和 owner_candidate_id 只能使用 audio_speakers 中提供的值；无法确定时全部为 null。",
                "不要根据常识补充日期；due_hint 只抄录原话中明确出现的截止线索。",
                "不要执行、发送、下单、付款或代表用户对外承诺。",
                "只输出 commitments 数组和严格 JSON。",
            ],
            "window": {
                "window_id": kwargs["window_id"],
                "captured_at_ms": kwargs["captured_at_ms"],
            },
            "transcript": kwargs["transcript"],
            "audio_speakers": [
                {
                    key: item.get(key)
                    for key in ("person_id", "candidate_id", "speaker_id", "name", "label")
                }
                for item in kwargs["audio_speakers"]
                if isinstance(item, dict)
            ],
            "evidence_refs": kwargs["evidence_refs"],
            "required_json_schema": {
                "commitments": [
                    {
                        "text": "明确未来行动",
                        "source_quote": "transcript 中的完整原话",
                        "owner_person_id": "输入 person_id 或 null",
                        "owner_candidate_id": "输入 candidate_id/speaker_id 或 null",
                        "owner_display": "输入姓名/候选名或未知说话人",
                        "due_hint": "原话截止线索或 null",
                        "commitment_strength": "explicit|soft|uncertain",
                        "confidence": 0.0,
                    }
                ]
            },
        }

    async def _complete_json(self, prompt: dict[str, Any]) -> dict[str, Any]:
        base_url = str(
            getattr(self.settings, "commitment_extraction_base_url", "") or ""
        ).rstrip("/")
        api_key = str(
            getattr(self.settings, "commitment_extraction_api_key", "") or ""
        )
        model = str(
            getattr(self.settings, "commitment_extraction_model", "") or ""
        )
        if not base_url or not api_key or not model:
            raise RuntimeError("commitment extraction provider not configured")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是 Beaver Memory 独立承诺抽取器，只输出严格 JSON；宁可漏掉也不要把软意向写成待办。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        token_field = "max_completion_tokens" if "xiaomimimo.com" in base_url else "max_tokens"
        payload[token_field] = int(
            getattr(self.settings, "commitment_extraction_max_tokens", 1600)
        )
        apply_qwen_request_options(payload, model=model)
        async with httpx.AsyncClient(
            timeout=float(
                getattr(self.settings, "commitment_extraction_timeout_seconds", 45)
            ),
            trust_env=False,
        ) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("provider returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ValueError("provider returned no JSON text")
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("provider JSON is not an object")
        return parsed

    @staticmethod
    def _result(status: str, *, errors: list[str] | None = None) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "status": status,
            "candidate_count": 0,
            "candidates": [],
            "schema_errors": errors or [],
        }
