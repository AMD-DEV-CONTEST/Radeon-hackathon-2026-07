from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import date as date_type
from datetime import datetime, time as time_type, timedelta, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import httpx

from glass_gateway.providers.llm.qwen_options import apply_qwen_request_options


DAILY_REVIEW_CONTRACT_VERSION = "daily-review-v1"
TODO_PROGRESS_CONTRACT_VERSION = "todo-progress-v1"


def _envelope_items(envelope: Any) -> list[dict[str, Any]]:
    if not isinstance(envelope, dict):
        return []
    data = envelope.get("data")
    if not isinstance(data, dict):
        return []
    for key in ("episodes", "items", "results"):
        values = data.get(key)
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
    return []


def _episode_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("memory_id") or item.get("episode_id") or "").strip()


def _episode_text(item: dict[str, Any]) -> str:
    for key in ("episode", "content", "text", "summary"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for child_key in ("text", "summary", "markdown", "body"):
                child = value.get(child_key)
                if isinstance(child, str) and child.strip():
                    return child.strip()
    return ""


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return _parse_datetime(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _episode_datetime(item: dict[str, Any]) -> datetime | None:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    for value in (
        item.get("timestamp"),
        item.get("captured_at_ms"),
        item.get("created_at"),
        item.get("updated_at"),
        metadata.get("timestamp"),
        metadata.get("captured_at_ms"),
        metadata.get("created_at"),
    ):
        parsed = _parse_datetime(value)
        if parsed is not None:
            return parsed
    return None


def _normalized_episode(item: dict[str, Any], *, timezone_name: str) -> dict[str, Any] | None:
    episode_id = _episode_id(item)
    content = _episode_text(item)
    captured_at = _episode_datetime(item)
    if not episode_id or not content or captured_at is None:
        return None
    local = captured_at.astimezone(ZoneInfo(timezone_name))
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "id": episode_id,
        "title": str(item.get("subject") or item.get("title") or item.get("summary") or "").strip(),
        "summary": str(item.get("summary") or "").strip(),
        "content": content,
        "timestamp": captured_at.isoformat(),
        "local_time": local.isoformat(),
        "local_date": local.date().isoformat(),
        "session_id": item.get("session_id") or metadata.get("session_id"),
        "source": {
            "id": episode_id,
            "session_id": item.get("session_id") or metadata.get("session_id"),
            "manifest": metadata.get("manifest") or metadata.get("bridge_manifest"),
            "memory_type": "episode",
        },
        "everos": item,
    }


def _content_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compact_text(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _valid_generated_item(
    item: Any,
    *,
    allowed_episode_ids: set[str],
    allowed_todo_ids: set[str],
    require_todo: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    text = _compact_text(item.get("text"), limit=1200)
    episode_ids = list(
        dict.fromkeys(
            str(value).strip()
            for value in item.get("source_episode_ids") or []
            if str(value).strip() in allowed_episode_ids
        )
    )
    todo_ids = list(
        dict.fromkeys(
            str(value).strip()
            for value in item.get("todo_ids") or []
            if str(value).strip() in allowed_todo_ids
        )
    )
    if not text or not episode_ids or (require_todo and not todo_ids):
        return None
    result = {
        "text": text,
        "source_episode_ids": episode_ids,
    }
    if todo_ids:
        result["todo_ids"] = todo_ids
    if item.get("start_at"):
        result["start_at"] = str(item["start_at"])[:80]
    if item.get("uncertain") is not None:
        result["uncertain"] = bool(item["uncertain"])
    if require_todo:
        change = str(item.get("change") or "").strip()
        if change:
            result["change"] = change[:80]
        result["todo_id"] = todo_ids[0]
    return result


def normalize_daily_review(
    raw: dict[str, Any],
    *,
    report_date: str,
    episodes: list[dict[str, Any]],
    todos: list[dict[str, Any]],
) -> dict[str, Any]:
    allowed_episode_ids = {str(item["id"]) for item in episodes}
    allowed_todo_ids = {str(item.get("id") or item.get("commitment_id")) for item in todos}

    def rows(key: str, limit: int, *, require_todo: bool = False) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in raw.get(key) or []:
            normalized = _valid_generated_item(
                value,
                allowed_episode_ids=allowed_episode_ids,
                allowed_todo_ids=allowed_todo_ids,
                require_todo=require_todo,
            )
            if normalized is None:
                continue
            fingerprint = _content_fingerprint(
                {
                    "text": re.sub(r"\W+", "", normalized["text"].casefold()),
                    "episodes": normalized["source_episode_ids"],
                    "todo": normalized.get("todo_ids"),
                }
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result.append(normalized)
            if len(result) >= limit:
                break
        return result

    timeline = rows("timeline", 12)
    notable = rows("notable_items", 8)
    special = rows("special_moments", 5)
    todo_changes = rows("todo_changes", 12, require_todo=True)
    overview = _compact_text(raw.get("overview"), limit=2400)
    if overview and not timeline and not notable and not special:
        overview = ""
    return {
        "contract_version": DAILY_REVIEW_CONTRACT_VERSION,
        "title": _compact_text(raw.get("title"), limit=160) or f"我的 {report_date} 日报",
        "overview": overview,
        "timeline": timeline,
        "notable_items": notable,
        "special_moments": special,
        "todo_changes": todo_changes,
    }


def _grounded_todo_change_rows(
    events: list[dict[str, Any]],
    todos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    todo_by_id = {
        str(item.get("id") or item.get("commitment_id") or ""): item for item in todos
    }
    labels = {
        "created": "新增待办",
        "progress": "待办有了新进展",
        "suspected_completed": "待办可能已经完成",
        "completed": "待办已确认完成",
        "done": "待办已确认完成",
        "open": "待办已重新打开",
        "in_progress": "待办已开始处理",
        "cancelled": "待办已取消",
    }
    rows: list[dict[str, Any]] = []
    for event in events:
        todo_id = str(event.get("todo_id") or "")
        todo = todo_by_id.get(todo_id)
        event_type = str(event.get("event_type") or "")
        if todo is None or event_type not in labels:
            continue
        row = {
            "text": f"{labels[event_type]}：{_compact_text(todo.get('text'), limit=800)}",
            "todo_id": todo_id,
            "todo_ids": [todo_id],
            "change": event_type,
            "source_episode_ids": [
                str(value)
                for value in event.get("source_episode_ids") or []
                if str(value).strip()
            ],
        }
        rows.append(row)
    return rows[:20]


class DailyReviewService:
    def __init__(
        self,
        settings: Any,
        *,
        everos_getter: Callable[[], Any],
        markdown_getter: Callable[[], Any],
        store_getter: Callable[[], Any],
        complete_json: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.settings = settings
        self._everos_getter = everos_getter
        self._markdown_getter = markdown_getter
        self._store_getter = store_getter
        self._complete_json_override = complete_json
        self._generation_lock = asyncio.Lock()

    @property
    def timezone_name(self) -> str:
        return str(getattr(self.settings, "daily_review_timezone", "Asia/Shanghai"))

    async def collect_episodes(self, report_date: str) -> list[dict[str, Any]]:
        target = date_type.fromisoformat(report_date)
        zone = ZoneInfo(self.timezone_name)
        start = datetime.combine(target, time_type.min, tzinfo=zone)
        end = start + timedelta(days=1)
        filters = {
            "timestamp": {
                "gte": int(start.timestamp() * 1000),
                "lt": int(end.timestamp() * 1000),
            }
        }
        raw: list[dict[str, Any]] = []
        everos_error: Exception | None = None
        for page in range(1, 21):
            try:
                envelope = await self._everos_getter().get_episodes(
                    self.settings.everos_user_id,
                    page=page,
                    page_size=100,
                    filters=filters,
                )
            except TypeError:
                envelope = await self._everos_getter().get_episodes(
                    self.settings.everos_user_id,
                    page=page,
                    page_size=100,
                )
            except Exception as exc:
                everos_error = exc
                break
            page_items = _envelope_items(envelope)
            raw.extend(page_items)
            if len(page_items) < 100:
                break

        if not raw:
            try:
                markdown = self._markdown_getter().get_episodes(
                    self.settings.everos_user_id,
                    page=1,
                    page_size=2000,
                    filters=filters,
                )
                raw = _envelope_items(markdown)
            except Exception:
                if everos_error is not None:
                    raise everos_error

        store = self._store_getter()
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw:
            episode = _normalized_episode(item, timezone_name=self.timezone_name)
            if episode is None or episode["local_date"] != report_date:
                continue
            projected = store.apply_corrections(
                target_type="episode",
                target_id=str(episode["id"]),
                source=episode,
            )
            if projected is None or str(projected["id"]) in seen:
                continue
            seen.add(str(projected["id"]))
            results.append(projected)
        results.sort(key=lambda item: str(item.get("timestamp") or ""))
        return results

    async def generate(
        self,
        report_date: str,
        *,
        generation_type: str = "manual",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not bool(getattr(self.settings, "daily_review_enabled", True)):
            raise RuntimeError("daily review is disabled")
        date_type.fromisoformat(report_date)
        key = idempotency_key or (
            f"manual:{report_date}:{datetime.now(timezone.utc).isoformat()}"
        )
        async with self._generation_lock:
            store = self._store_getter()
            existing = store.daily_report_by_idempotency_key(key)
            if existing is not None:
                return existing
            report = store.start_daily_report_version(
                date=report_date,
                generation_type=generation_type,
                idempotency_key=key,
            )
            try:
                episodes = await self.collect_episodes(report_date)
                todos = store.list_todos()
                todo_changes = store.todo_events_for_date(
                    report_date,
                    timezone_name=self.timezone_name,
                )
                snapshot = {
                    "episode_ids": [item["id"] for item in episodes],
                    "todo_ids": [
                        str(item.get("id") or item.get("commitment_id")) for item in todos
                    ],
                    "todo_event_ids": [item.get("id") for item in todo_changes],
                }
                if not episodes:
                    content = {
                        "contract_version": DAILY_REVIEW_CONTRACT_VERSION,
                        "title": f"我的 {report_date} 日报",
                        "overview": "今天暂无足够记忆。",
                        "timeline": [],
                        "notable_items": [],
                        "special_moments": [],
                        "todo_changes": _grounded_todo_change_rows(todo_changes, todos),
                    }
                else:
                    prompt = self._daily_prompt(
                        report_date=report_date,
                        episodes=episodes,
                        todos=todos,
                        todo_changes=todo_changes,
                    )
                    raw = (
                        await self._complete_json_override(prompt)
                        if self._complete_json_override is not None
                        else await self._complete_json(prompt)
                    )
                    content = normalize_daily_review(
                        raw,
                        report_date=report_date,
                        episodes=episodes,
                        todos=todos,
                    )
                    content["todo_changes"] = _grounded_todo_change_rows(
                        todo_changes,
                        todos,
                    )
                    if not any(
                        content[key]
                        for key in ("timeline", "notable_items", "special_moments")
                    ):
                        raise ValueError("daily review contained no grounded items")
                return store.complete_daily_report_version(
                    str(report["id"]),
                    content=content,
                    input_snapshot=snapshot,
                    input_fingerprint=_content_fingerprint(
                        {
                            "episodes": [
                                {
                                    "id": item["id"],
                                    "content": item.get("content"),
                                    "timestamp": item.get("timestamp"),
                                }
                                for item in episodes
                            ],
                            "todos": todos,
                            "todo_changes": todo_changes,
                        }
                    ),
                    aggregation_status="final",
                    model=str(getattr(self.settings, "daily_review_model", "") or "none"),
                    prompt_version=DAILY_REVIEW_CONTRACT_VERSION,
                )
            except Exception as exc:
                return store.fail_daily_report_version(
                    str(report["id"]),
                    error=f"{type(exc).__name__}: {exc}",
                )

    async def evaluate_new_episodes(self, report_dates: list[str]) -> list[dict[str, Any]]:
        store = self._store_getter()
        results: list[dict[str, Any]] = []
        for report_date in dict.fromkeys(report_dates):
            for episode in await self.collect_episodes(report_date):
                episode_id = str(episode["id"])
                fingerprint = _content_fingerprint(episode.get("content"))
                if store.todo_episode_processed(episode_id, fingerprint):
                    continue
                results.extend(await self.evaluate_todos_for_episode(episode))
                store.mark_todo_episode_processed(episode_id, fingerprint)
        return results

    async def evaluate_todos_for_episode(
        self,
        episode: dict[str, Any],
    ) -> list[dict[str, Any]]:
        store = self._store_getter()
        candidates = [
            item
            for item in store.list_todos()
            if item.get("status")
            in {"confirmed", "open", "in_progress", "suspected_completed"}
        ][:30]
        if not candidates:
            return []
        prompt = {
            "task": "判断当前 Episode 是否为某条长期待办提供了明确进展或完成证据。",
            "rules": [
                "只输出 unrelated、progress 或 suspected_completed。",
                "正在做、准备做、计划做不等于已经完成。",
                "evidence_text 必须逐字摘自 episode.content。",
                "模型无权把待办直接标记为 completed。",
                "只输出严格 JSON。",
            ],
            "episode": {
                "id": episode["id"],
                "content": episode.get("content"),
                "timestamp": episode.get("timestamp"),
            },
            "todos": [
                {
                    "todo_id": item.get("id") or item.get("commitment_id"),
                    "text": item.get("text"),
                    "status": item.get("status"),
                    "due_at": item.get("normalized_due_at"),
                }
                for item in candidates
            ],
            "required_json_schema": {
                "updates": [
                    {
                        "todo_id": "输入中的 todo_id",
                        "decision": "unrelated|progress|suspected_completed",
                        "evidence_text": "episode.content 的逐字片段",
                        "confidence": 0.0,
                    }
                ]
            },
        }
        try:
            raw = (
                await self._complete_json_override(prompt)
                if self._complete_json_override is not None
                else await self._complete_json(prompt)
            )
        except Exception:
            return []
        allowed = {
            str(item.get("id") or item.get("commitment_id")): item for item in candidates
        }
        episode_text = str(episode.get("content") or "")
        results: list[dict[str, Any]] = []
        for item in raw.get("updates") or []:
            if not isinstance(item, dict):
                continue
            todo_id = str(item.get("todo_id") or "")
            decision = str(item.get("decision") or "")
            evidence_text = _compact_text(item.get("evidence_text"), limit=1200)
            if (
                todo_id not in allowed
                or decision not in {"progress", "suspected_completed"}
                or not evidence_text
                or evidence_text not in episode_text
            ):
                continue
            confidence = item.get("confidence")
            confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.0
            results.append(
                store.record_todo_progress(
                    todo_id=todo_id,
                    decision=decision,
                    episode_id=str(episode["id"]),
                    evidence_text=evidence_text,
                    confidence=max(0.0, min(1.0, confidence)),
                    occurred_at=str(episode.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                )
            )
        return results

    def _daily_prompt(
        self,
        *,
        report_date: str,
        episodes: list[dict[str, Any]],
        todos: list[dict[str, Any]],
        todo_changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "task": "根据用户当天真实 Episode，生成一份中文第一人称日报。",
            "date": report_date,
            "timezone": self.timezone_name,
            "rules": [
                "timeline 回答我今天主要做了什么，按时间顺序合并同一事件，不逐条复述窗口。",
                "notable_items 只写未收尾、重要决定、明显变化、临近截止或之后可能需要回看的信息。",
                "special_moments 只写有新鲜感、情绪意义、成就感或明显变化的时刻；没有则返回空数组。",
                "所有事实必须只来自输入 Episode；每项必须填写真实 source_episode_ids。",
                "overview 只能总结其他有来源条目，不得引入新事实。",
                "不确定内容自然使用“可能、似乎、像是”，不要硬写成事实。",
                "只输出 required_json_schema 对应的严格 JSON。",
            ],
            "episodes": [
                {
                    "episode_id": item["id"],
                    "local_time": item.get("local_time"),
                    "title": item.get("title"),
                    "content": item.get("content"),
                }
                for item in episodes
            ],
            "todos": [
                {
                    "todo_id": item.get("id") or item.get("commitment_id"),
                    "text": item.get("text"),
                    "status": item.get("status"),
                    "due_at": item.get("normalized_due_at"),
                }
                for item in todos
            ],
            "todo_changes_today": todo_changes,
            "required_json_schema": {
                "title": "我的日期",
                "overview": "不引入新事实的整体概括",
                "timeline": [
                    {
                        "text": "第一人称事件描述",
                        "source_episode_ids": ["episode-id"],
                        "start_at": "ISO 时间",
                    }
                ],
                "notable_items": [
                    {
                        "text": "值得留意的内容",
                        "source_episode_ids": ["episode-id"],
                        "todo_ids": ["todo-id"],
                        "uncertain": False,
                    }
                ],
                "special_moments": [
                    {
                        "text": "特别瞬间",
                        "source_episode_ids": ["episode-id"],
                    }
                ],
                "todo_changes": [
                    {
                        "text": "待办变化",
                        "source_episode_ids": ["episode-id"],
                        "todo_ids": ["todo-id"],
                        "change": "progress|suspected_completed|completed|created|overdue",
                    }
                ],
            },
        }

    async def _complete_json(self, prompt: dict[str, Any]) -> dict[str, Any]:
        base_url = str(getattr(self.settings, "daily_review_base_url", "") or "").rstrip("/")
        api_key = str(getattr(self.settings, "daily_review_api_key", "") or "")
        model = str(getattr(self.settings, "daily_review_model", "") or "")
        if not base_url or not api_key or not model:
            raise RuntimeError("daily review provider not configured")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是 Beaver Memory 的真实日报与待办进展整理器，只输出严格 JSON，所有结论必须可追溯到输入 Episode。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        token_field = "max_completion_tokens" if "xiaomimimo.com" in base_url else "max_tokens"
        payload[token_field] = int(getattr(self.settings, "daily_review_max_tokens", 4000))
        apply_qwen_request_options(payload, model=model)
        async with httpx.AsyncClient(
            timeout=float(getattr(self.settings, "daily_review_timeout_seconds", 60)),
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


class DailyReviewScheduler:
    def __init__(
        self,
        settings: Any,
        service: DailyReviewService,
    ) -> None:
        self.settings = settings
        self.service = service
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if not bool(getattr(self.settings, "daily_review_enabled", True)) or not bool(
            getattr(self.settings, "daily_review_scheduler_enabled", True)
        ):
            return
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self, now: datetime | None = None) -> dict[str, Any]:
        zone = ZoneInfo(self.service.timezone_name)
        local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
        hour = max(0, min(23, int(getattr(self.settings, "daily_review_schedule_hour", 22))))
        target_date = local_now.date() if local_now.hour >= hour else local_now.date() - timedelta(days=1)
        report_date = target_date.isoformat()
        key = f"scheduled:{report_date}:{hour:02d}:00"
        report = self.service._store_getter().daily_report_by_idempotency_key(key)
        if report is None:
            report = await self.service.generate(
                report_date,
                generation_type="scheduled",
                idempotency_key=key,
            )
        scan_dates = [local_now.date().isoformat(), (local_now.date() - timedelta(days=1)).isoformat()]
        todo_updates = await self.service.evaluate_new_episodes(scan_dates)
        return {"daily_report": report, "todo_updates": todo_updates}

    async def _loop(self) -> None:
        initial_delay = float(getattr(self.settings, "daily_review_initial_delay_seconds", 60))
        interval = float(getattr(self.settings, "daily_review_poll_seconds", 60))
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=max(0.1, initial_delay))
            return
        except asyncio.TimeoutError:
            pass
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(5.0, interval))
            except asyncio.TimeoutError:
                continue
