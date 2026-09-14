from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Mapping
from zoneinfo import ZoneInfo

import httpx

from glass_gateway.providers.llm.qwen_options import apply_qwen_request_options

from glass_gateway.evaluation.retrieval_production import (
    RetrievedEpisode,
    rerank_candidates,
)


CompleteJSON = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

SEARCH_OBJECTS_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_objects",
        "description": "在已经保存的物品观察中查找某个物品、它出现的位置与对应 Capsule 证据；不会在查询时重新运行视觉检测。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "用户关于物品的自然语言问题，例如‘我最后在哪里看到黑色眼镜盒？’",
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _observation_id(item: Mapping[str, Any]) -> str:
    return str(item.get("observation_id") or item.get("id") or "").strip()


def _object_document(item: Mapping[str, Any]) -> str:
    values = [
        item.get("object_label_raw") or item.get("object_label"),
        item.get("canonical_name"),
        *(item.get("aliases") or []),
        item.get("normalized_label"),
        item.get("personal_object_id"),
        item.get("visible_description"),
        item.get("relation"),
        item.get("location_hint"),
        "最近看到",
        "物品位置",
    ]
    return "；".join(dict.fromkeys(value for value in (_text(v) for v in values) if value))


def _display_time(value: Any) -> str | None:
    try:
        timestamp_ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=ZoneInfo("Asia/Shanghai"),
    ).strftime("%Y-%m-%d %H:%M:%S")


def _extract_json(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I | re.S)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, flags=re.S)
        if not match:
            raise ValueError("LLM response does not contain a JSON object")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM response is not a JSON object")
    return parsed


class ObjectSearchTool:
    """Natural-language tool over precomputed, auditable object observations."""

    def __init__(
        self,
        settings: Any,
        review_store: Any,
        *,
        post_json: Callable[[str, dict[str, object]], dict[str, object]],
        complete_json: CompleteJSON | None = None,
    ) -> None:
        self.settings = settings
        self.review_store = review_store
        self.post_json = post_json
        self.complete_json_override = complete_json

    async def search(self, *, question: str, top_k: int = 8) -> dict[str, Any]:
        started = time.perf_counter()
        question = _text(question)
        degraded: list[str] = []
        snapshot = self.review_store.snapshot()
        observations = [
            dict(item)
            for item in snapshot.get("object_observations", [])
            if isinstance(item, Mapping)
            and item.get("state", "semantic_only")
            in {"detector_only", "semantic_only", "fused"}
            and item.get("memory_value", "memory_critical")
            in {"memory_critical", "context_only"}
        ]
        confirmed_objects = [
            dict(item)
            for item in snapshot.get("confirmed_objects", [])
            if isinstance(item, Mapping)
        ]
        if not observations:
            return self._response(
                question=question,
                parsed_query=self._fallback_parse(question),
                status="not_found",
                answer="还没有已保存且值得查询的物品观察。",
                selected=None,
                candidates=[],
                degraded=degraded,
                started=started,
                llm_used=False,
            )

        llm_used = False
        try:
            parsed_query = await self._complete_json(
                self._parse_prompt(question, confirmed_objects, observations)
            )
            parsed_query = self._normalize_parsed_query(parsed_query, question)
            llm_used = True
        except Exception as exc:
            parsed_query = self._fallback_parse(question)
            degraded.append(f"query_parser_unavailable:{type(exc).__name__}")

        exact_observations = [
            item
            for item in observations
            if self._has_object_term_support(question, parsed_query, item)
        ]
        retrieval_observations = exact_observations or observations

        candidate_rows = [
            RetrievedEpisode(
                document_id=_observation_id(item),
                episode_id=str(item.get("source_capsule_id") or _observation_id(item)),
                episode_text=_object_document(item),
                score=self._lexical_score(question, parsed_query, item),
            )
            for item in retrieval_observations
            if _observation_id(item)
        ]
        ranked = sorted(candidate_rows, key=lambda row: (-row.score, row.document_id))
        try:
            ranked = await asyncio.to_thread(
                rerank_candidates,
                {
                    "query_id": f"object-web-{int(time.time() * 1000)}",
                    "query_type": "text",
                    "query_text": question,
                },
                ranked[: max(20, top_k)],
                dataset_parent=None,
                reranker_url=self.settings.memory_search_reranker_url,
                reranker_model=self.settings.memory_search_reranker_model,
                post_json=self.post_json,
            )
            ranked = sorted(ranked, key=lambda row: (-row.score, row.document_id))
        except Exception as exc:
            degraded.append(f"object_reranker_unavailable:{type(exc).__name__}")

        by_id = {_observation_id(item): item for item in retrieval_observations}
        candidate_limit = max(1, min(20, top_k))
        candidates = [by_id[row.document_id] for row in ranked[:candidate_limit] if row.document_id in by_id]
        score_by_id = {row.document_id: float(row.score) for row in ranked}
        selection: dict[str, Any] = {}
        judge_completed = False
        try:
            selection = await self._complete_json(
                self._selection_prompt(question, parsed_query, candidates)
            )
            llm_used = True
            judge_completed = True
        except Exception as exc:
            degraded.append(f"candidate_judge_unavailable:{type(exc).__name__}")

        allowed_ids = {_observation_id(item) for item in candidates}
        selected_id = str(selection.get("selected_observation_id") or "").strip()
        selected = by_id.get(selected_id) if selected_id in allowed_ids else None
        time_intent = parsed_query.get("time_intent")
        if (
            selected is not None
            and exact_observations
            and candidates
            and time_intent in {"last_seen", "first_seen"}
            and not parsed_query.get("attributes")
            and parsed_query.get("relation_intent", "any") == "any"
        ):
            # The LLM judges semantic support, but an explicit, unconstrained
            # temporal intent has deterministic semantics.  Do not let the
            # judge replace "last/first seen" with the most descriptive hit.
            chronological = self._fallback_select(candidates, parsed_query)
            if chronological is not None and chronological is not selected:
                selected = chronological
                selected_id = _observation_id(selected)
                selection["selected_observation_id"] = selected_id
                selection["supporting_observation_ids"] = [selected_id]
                selection["reason"] = (
                    "候选物品名称已匹配；按用户明确的"
                    f"{'最后一次' if time_intent == 'last_seen' else '第一次'}"
                    "时间意图选择。"
                )
        if (
            selected is None
            and not judge_completed
            and candidates
            and self._fallback_has_support(
                question,
                parsed_query,
                candidates,
                score_by_id,
            )
        ):
            selected = self._fallback_select(candidates, parsed_query)
        if selected is None:
            status = "not_found"
            answer = "没有找到足够相关的已保存物品观察。"
        else:
            status = "ambiguous" if bool(selection.get("ambiguous")) or selected.get("instance_ambiguity") else "found"
            answer = self._grounded_answer(selected, ambiguous=status == "ambiguous")

        public_candidates = (
            [
                self._public_candidate(
                    item,
                    score=score_by_id.get(_observation_id(item), 0.0),
                )
                for item in candidates
            ]
            if selected is not None
            else []
        )
        return self._response(
            question=question,
            parsed_query=parsed_query,
            status="degraded" if selected is not None and degraded else status,
            answer=answer,
            selected=self._public_candidate(selected, score=score_by_id.get(_observation_id(selected), 0.0)) if selected else None,
            candidates=public_candidates,
            degraded=degraded,
            started=started,
            llm_used=llm_used,
            judge={
                "ambiguous": bool(selection.get("ambiguous")),
                "reason": _text(selection.get("reason"))[:300] or None,
                "supporting_observation_ids": [
                    value for value in selection.get("supporting_observation_ids", [])
                    if isinstance(value, str) and value in allowed_ids
                ][:8],
            },
        )

    async def _complete_json(self, prompt: dict[str, Any]) -> dict[str, Any]:
        if self.complete_json_override is not None:
            return await self.complete_json_override(prompt)
        base_url = str(self.settings.memory_context_base_url or "").rstrip("/")
        api_key = str(self.settings.memory_context_api_key or "")
        model = str(self.settings.memory_context_model or "")
        if not base_url or not api_key or not model:
            raise RuntimeError("object query LLM is not configured")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是物品记忆检索工具，只输出严格 JSON object，不编造候选或位置。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        token_field = "max_completion_tokens" if "xiaomimimo.com" in base_url else "max_tokens"
        payload[token_field] = min(1200, int(self.settings.memory_context_max_tokens))
        apply_qwen_request_options(payload, model=model)
        async with httpx.AsyncClient(
            timeout=self.settings.memory_context_timeout_seconds,
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
            raise ValueError("LLM returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ValueError("LLM returned no JSON text")
        return _extract_json(content)

    @staticmethod
    def _parse_prompt(
        question: str,
        confirmed_objects: list[dict[str, Any]],
        observations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        catalog = []
        for item in confirmed_objects:
            catalog.append({
                "label": item.get("label"),
                "aliases": item.get("aliases") or [],
                "personal_object_id": item.get("personal_object_id"),
            })
        known_labels = sorted({
            _text(item.get("object_label_raw") or item.get("object_label"))
            for item in observations
            if _text(item.get("object_label_raw") or item.get("object_label"))
        })
        return {
            "task": "把用户问话转换为物品观察检索参数。只做意图解析，不回答问题。",
            "question": question,
            "known_object_catalog": catalog[:100],
            "known_labels": known_labels[:200],
            "required_json_schema": {
                "object_terms": ["物品名称、别名、外观词或个人物品 id"],
                "attributes": ["颜色、材质、大小等限制"],
                "time_intent": "last_seen|first_seen|any",
                "relation_intent": "held|placed_on|visible_at|moved|searched_for|any",
                "asks_location": True,
                "asks_evidence": True,
            },
        }

    @staticmethod
    def _selection_prompt(
        question: str,
        parsed_query: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rows = []
        for item in candidates:
            rows.append({
                "observation_id": _observation_id(item),
                "object_label": item.get("object_label_raw") or item.get("object_label"),
                "state": item.get("state"),
                "personal_object_id": item.get("personal_object_id"),
                "visible_description": item.get("visible_description"),
                "relation": item.get("relation"),
                "location_hint": item.get("location_hint"),
                "captured_at_ms": item.get("captured_at_ms"),
                "semantic_confidence": item.get("semantic_confidence"),
                "instance_ambiguity": item.get("instance_ambiguity"),
                "evidence_available": item.get("evidence_available", True),
                "source_capsule_id": item.get("source_capsule_id"),
            })
        return {
            "task": "从候选中选择最能回答问题的一条物品观察。只能返回候选里的 observation_id；时间、实例与位置冲突时应标记 ambiguous。",
            "question": question,
            "parsed_query": parsed_query,
            "candidates": rows,
            "required_json_schema": {
                "selected_observation_id": "候选 id 或 null",
                "supporting_observation_ids": ["候选 id"],
                "ambiguous": False,
                "reason": "为何选择；不得补充候选中不存在的事实",
            },
        }

    @staticmethod
    def _normalize_parsed_query(value: dict[str, Any], question: str) -> dict[str, Any]:
        terms = [_text(item)[:100] for item in value.get("object_terms", []) if _text(item)]
        attributes = [_text(item)[:100] for item in value.get("attributes", []) if _text(item)]
        time_intent = value.get("time_intent")
        if time_intent not in {"last_seen", "first_seen", "any"}:
            time_intent = "last_seen" if any(word in question for word in ("最后", "上次", "最近")) else "any"
        relation = value.get("relation_intent")
        if relation not in {"held", "placed_on", "visible_at", "moved", "searched_for", "any"}:
            relation = "any"
        return {
            "object_terms": terms or [question],
            "attributes": attributes,
            "time_intent": time_intent,
            "relation_intent": relation,
            "asks_location": bool(value.get("asks_location", True)),
            "asks_evidence": bool(value.get("asks_evidence", True)),
        }

    @staticmethod
    def _fallback_parse(question: str) -> dict[str, Any]:
        return {
            "object_terms": [question],
            "attributes": [],
            "time_intent": "last_seen" if any(word in question for word in ("最后", "上次", "最近")) else "any",
            "relation_intent": "any",
            "asks_location": any(word in question for word in ("哪里", "哪儿", "哪裡", "在哪", "位置")),
            "asks_evidence": True,
        }

    @staticmethod
    def _lexical_score(question: str, parsed: dict[str, Any], item: Mapping[str, Any]) -> float:
        haystack = _object_document(item).casefold()
        terms = [question, *parsed.get("object_terms", []), *parsed.get("attributes", [])]
        score = sum(1.0 for term in terms if _text(term).casefold() in haystack)
        memory_bonus = 0.05 if item.get("memory_value") == "memory_critical" else 0.0
        return score + float(item.get("semantic_confidence") or 0.0) * 0.1 + memory_bonus

    @staticmethod
    def _has_object_term_support(
        question: str,
        parsed: dict[str, Any],
        item: Mapping[str, Any],
    ) -> bool:
        names = [
            item.get("object_label_raw"),
            item.get("object_label"),
            item.get("canonical_name"),
            item.get("normalized_label"),
            item.get("personal_object_id"),
            *(item.get("aliases") or []),
        ]
        normalized_names = [
            _text(name).casefold() for name in names if _text(name)
        ]
        terms = [
            _text(term).casefold()
            for term in parsed.get("object_terms", [])
            if _text(term)
        ]
        if any(
            term in name or name in term
            for term in terms
            for name in normalized_names
        ):
            return True
        normalized_question = question.casefold()
        return any(name in normalized_question for name in normalized_names)

    @staticmethod
    def _fallback_select(candidates: list[dict[str, Any]], parsed: dict[str, Any]) -> dict[str, Any] | None:
        if not candidates:
            return None
        direction = -1 if parsed.get("time_intent") == "last_seen" else 1
        if parsed.get("time_intent") in {"last_seen", "first_seen"}:
            return sorted(candidates, key=lambda item: direction * int(item.get("captured_at_ms") or 0))[0]
        return candidates[0]

    @staticmethod
    def _fallback_has_support(
        question: str,
        parsed: dict[str, Any],
        candidates: list[dict[str, Any]],
        score_by_id: dict[str, float],
    ) -> bool:
        needle = question.casefold()
        for item in candidates:
            names = [
                item.get("object_label_raw"),
                item.get("object_label"),
                item.get("canonical_name"),
                item.get("normalized_label"),
                item.get("personal_object_id"),
                *(item.get("aliases") or []),
            ]
            if any(_text(name).casefold() in needle for name in names if _text(name)):
                return True
        parsed_terms = [
            _text(value).casefold()
            for value in [*parsed.get("object_terms", []), *parsed.get("attributes", [])]
            if _text(value)
        ]
        if any(
            term in _object_document(item).casefold()
            for term in parsed_terms
            for item in candidates
        ):
            return True
        return max(score_by_id.values(), default=0.0) >= 0.4

    @staticmethod
    def _grounded_answer(item: Mapping[str, Any], *, ambiguous: bool) -> str:
        label = _text(item.get("object_label_raw") or item.get("object_label")) or "该物品"
        location = _text(item.get("location_hint"))
        when = _display_time(item.get("captured_at_ms"))
        detector_only = item.get("state") == "detector_only"
        if location:
            answer = f"{label}最近的候选记录是在{location}"
        else:
            answer = f"找到了{label}的视觉检测候选，但没有可靠的位置描述" if detector_only else f"找到了{label}的候选记录，但没有可靠的位置描述"
        if when:
            answer += f"（北京时间 {when}）"
        answer += "。"
        if detector_only:
            answer += " 这条记录尚未经过物品语义卡片确认，不能作为可靠 Last-seen。"
        if ambiguous:
            answer += " 画面里存在同类物品或证据冲突，暂时不能确认是同一个实例。"
        return answer

    @staticmethod
    def _public_candidate(item: Mapping[str, Any], *, score: float) -> dict[str, Any]:
        return {
            **dict(item),
            "retrieval_score": float(score),
            "display_time": _display_time(item.get("captured_at_ms")),
            "capsule_id": item.get("source_capsule_id"),
        }

    @staticmethod
    def _response(
        *,
        question: str,
        parsed_query: dict[str, Any],
        status: str,
        answer: str,
        selected: dict[str, Any] | None,
        candidates: list[dict[str, Any]],
        degraded: list[str],
        started: float,
        llm_used: bool,
        judge: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "tool_name": "search_objects",
            "tool_call": {"question": question, "parsed_query": parsed_query},
            "answer_status": status,
            "answer": answer,
            "selected_observation": selected,
            "candidate_capsules": candidates,
            "judge": judge or {},
            "retrieval": {
                "llm_used": llm_used,
                "precomputed_observations_only": True,
                "degraded": bool(degraded),
                "degraded_reasons": list(dict.fromkeys(degraded)),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        }
