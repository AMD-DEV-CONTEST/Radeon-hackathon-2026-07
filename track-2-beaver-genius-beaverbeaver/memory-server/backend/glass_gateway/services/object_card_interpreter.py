from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from glass_gateway.providers.llm.qwen_options import (
    apply_qwen_request_options,
    post_chat_completion,
)
from glass_gateway.services.memory_review_store import MemoryReviewStore
from glass_gateway.services.object_memory import ObjectAliasRegistry


_CONTRACT_VERSION = "object-card-v2-semantic-supplement"
_MERGE_DECISIONS = {"merge_existing", "create_new", "uncertain", "reject_candidate"}
_MEMORY_VALUES = {"memory_critical", "context_only", "ignore"}
_CARD_FIELDS = {
    "candidate_id",
    "canonical_name",
    "normalized_label",
    "visible_description",
    "location_hint",
    "relation_to_wearer",
    "memory_value",
    "merge_decision",
    "merge_target_observation_id",
    "semantic_confidence",
    "uncertainty",
}
_SEMANTIC_CARD_FIELDS = {
    "canonical_name",
    "normalized_label",
    "aliases",
    "visible_description",
    "location_hint",
    "relation_to_wearer",
    "memory_value",
    "merge_decision",
    "merge_target_observation_id",
    "semantic_confidence",
    "uncertainty",
    "supporting_evidence_ids",
}


class OpenAICompatibleObjectCardInterpreter:
    """Second MiMo pass over YOLOE candidates plus salient missed objects."""

    def __init__(self, settings: Any, store: MemoryReviewStore) -> None:
        self.settings = settings
        self.store = store

    async def process_window(
        self,
        *,
        boot_session_id: str,
        window_id: str,
        captured_at_ms: int,
        source_capsule_id: str,
        caption: str,
        images: list[dict[str, Any]],
        object_perception: dict[str, Any],
    ) -> dict[str, Any]:
        candidates = _aggregate_candidates(window_id, object_perception, images)
        available_evidence_ids = [
            str(item.get("id"))
            for item in images
            if item.get("id") and _image_data_url(item.get("uri"))
        ]
        if not candidates and not available_evidence_ids:
            return {
                "contract_version": _CONTRACT_VERSION,
                "status": "no_candidates",
                "candidate_count": 0,
                "semantic_only_count": 0,
                "observations": [],
                "schema_errors": [],
            }

        detector_rows = []
        for candidate in candidates:
            detector_rows.append(
                self.store.upsert_detector_object_observation(
                    object_label_raw=candidate["label"],
                    confidence=candidate["confidence"],
                    captured_at_ms=captured_at_ms,
                    boot_session_id=boot_session_id,
                    window_id=window_id,
                    evidence_ids=candidate["evidence_ids"],
                    evidence_uris=candidate["evidence_uris"],
                    detector_job_ids=candidate["detector_job_ids"],
                    bbox_evidence=candidate["bbox_evidence"],
                    source_model=str(candidate.get("model_id") or "yoloe-26s"),
                    vocabulary_hash=candidate.get("vocabulary_hash"),
                    late=bool(candidate.get("late")),
                )
            )
        for candidate, row in zip(candidates, detector_rows, strict=True):
            candidate["candidate_id"] = row["observation_id"]
            candidate["normalized_label"] = row["normalized_label"]

        historical = _historical_candidates(self.store.snapshot(), candidates)
        started = time.perf_counter()
        try:
            raw, provider_meta = await self._complete_json(
                candidates=candidates,
                historical=historical,
                caption=caption,
                images=images,
            )
            cards, semantic_cards, errors = _normalize_cards(
                raw,
                candidates,
                historical,
                available_evidence_ids=available_evidence_ids,
                allow_partial_candidates=bool(
                    getattr(
                        self.settings,
                        "object_card_allow_partial_candidates",
                        False,
                    )
                ),
            )
        except Exception as exc:
            return {
                "contract_version": _CONTRACT_VERSION,
                "status": "failed",
                "candidate_count": len(candidates),
                "semantic_only_count": 0,
                "observations": detector_rows,
                "schema_errors": [f"{type(exc).__name__}: {exc}"],
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        if errors:
            return {
                "contract_version": _CONTRACT_VERSION,
                "status": "failed",
                "candidate_count": len(candidates),
                "semantic_only_count": 0,
                "observations": detector_rows,
                "schema_errors": errors,
                "raw_model_output": raw,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "usage": provider_meta.get("usage") or {},
            }

        history_by_id = {
            str(item.get("observation_id") or item.get("id")): item for item in historical
        }
        promoted = []
        for card in cards:
            candidate_id = str(card["candidate_id"])
            if card["merge_decision"] == "reject_candidate" or card["memory_value"] == "ignore":
                self.store.reject_object_observation(
                    candidate_id,
                    reason=str(card.get("uncertainty") or "semantic_reject"),
                )
                continue
            merge_target = history_by_id.get(str(card.get("merge_target_observation_id") or ""))
            identity_id = (
                str(merge_target.get("object_identity_id") or "") if merge_target else None
            )
            item = self.store.promote_object_observation(
                observation_id=candidate_id,
                card=card,
                source_capsule_id=source_capsule_id,
                source_model=str(self.settings.object_card_model or "mimo-v2.5"),
                source_prompt_version=_CONTRACT_VERSION,
                object_identity_id=identity_id,
            )
            if item:
                promoted.append(item)
        semantic_only = []
        image_uri_by_id = {
            str(item.get("id")): str(item.get("uri"))
            for item in images
            if item.get("id") and item.get("uri")
        }
        for card in semantic_cards:
            if card["memory_value"] == "ignore" or card["semantic_confidence"] < 0.55:
                continue
            merge_target = history_by_id.get(
                str(card.get("merge_target_observation_id") or "")
            )
            evidence_ids = list(card["supporting_evidence_ids"])
            item = self.store.add_semantic_object_observation(
                object_label_raw=card["canonical_name"],
                normalized_label=card["normalized_label"],
                personal_object_id=None,
                visible_description=card.get("visible_description"),
                relation=card.get("relation_to_wearer"),
                location_hint=card.get("location_hint"),
                memory_value=card["memory_value"],
                semantic_confidence=card["semantic_confidence"],
                captured_at_ms=captured_at_ms,
                boot_session_id=boot_session_id,
                window_id=window_id,
                evidence_ids=evidence_ids,
                evidence_uris=[
                    image_uri_by_id[evidence_id]
                    for evidence_id in evidence_ids
                    if image_uri_by_id.get(evidence_id)
                ],
                evidence_available=bool(evidence_ids),
                source_capsule_id=source_capsule_id,
                source_model=str(self.settings.object_card_model or "mimo-v2.5"),
                source_prompt_version=_CONTRACT_VERSION,
                detector_job_ids=[],
                aliases=card.get("aliases") or [],
                object_identity_id=(
                    str(merge_target.get("object_identity_id") or "")
                    if merge_target
                    else None
                ),
                merge_decision=card.get("merge_decision"),
                merge_target_observation_id=card.get("merge_target_observation_id"),
                instance_ambiguity=card.get("merge_decision") == "uncertain",
            )
            semantic_only.append(item)
        return {
            "contract_version": _CONTRACT_VERSION,
            "status": "completed",
            "candidate_count": len(candidates),
            "semantic_only_count": len(semantic_only),
            "observations": [
                *promoted,
                *semantic_only,
                *[
                    row
                    for row in detector_rows
                    if row["observation_id"] not in {item["observation_id"] for item in promoted}
                ],
            ],
            "schema_errors": [],
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "usage": provider_meta.get("usage") or {},
        }

    async def _complete_json(
        self,
        *,
        candidates: list[dict[str, Any]],
        historical: list[dict[str, Any]],
        caption: str,
        images: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.settings.object_card_enabled:
            raise RuntimeError("object card interpreter disabled")
        base_url = str(self.settings.object_card_base_url or "").rstrip("/")
        api_key = str(self.settings.object_card_api_key or "")
        model = str(self.settings.object_card_model or "")
        if not base_url or not api_key or not model:
            raise RuntimeError("object card provider not configured")
        prompt = {
            "task": "这是独立物品链路。根据图片和只读 caption 填写物品卡片：处理 YOLOE 候选，同时补充 YOLOE 明显漏掉但对个人记忆有价值的显著物品。不要描述整个经历。",
            "rules": [
                "cards 只处理 candidates 中的候选，不得改变候选类别。",
                "semantic_only_cards 只补充图片或 caption 明确支持、但 candidates 没有覆盖的显著物品；最多 5 个。",
                "优先补充用户正在拿、使用、寻找、移动、讨论或之后可能查询的物品；不要罗列墙、家具、餐具等普通背景。",
                "semantic_only_cards 必须引用 available_evidence_ids 中至少一个图片证据，并提供便于中英文搜索的 aliases。",
                "canonical_name、visible_description、location_hint、uncertainty 等面向用户的文字必须使用简体中文；品牌名和型号可保留原文，normalized_label 和 aliases 可含英文用于检索。",
                "位置描述以佩戴者第一人称书写，例如‘我手中’‘我面前的桌上’，不要写‘用户手中’。",
                "同标签不是同一实例的充分条件；不能确认时使用 uncertain。",
                "merge_existing 只能选择 historical_candidates 中语义上同一物品的 observation_id。",
                "位置只写画面可支持的相对位置；无法判断时为 null，不得编造房间或所有权。",
                "普通背景物品可以标记 context_only 或 ignore；随身关键物品才标记 memory_critical。",
                "只输出 cards 和 semantic_only_cards 两个数组及严格字段，不输出经历 caption、人物、会议或其他字段。",
            ],
            "current_caption_read_only": caption[:800],
            "available_evidence_ids": [
                {
                    "evidence_id": item.get("id"),
                    "captured_at_ms": item.get("captured_at_ms"),
                }
                for item in images
                if item.get("id") and _image_data_url(item.get("uri"))
            ],
            "candidates": [
                {key: value for key, value in item.items() if key != "evidence_uris"}
                for item in candidates
            ],
            "historical_candidates": [
                {
                    key: item.get(key)
                    for key in (
                        "observation_id",
                        "object_identity_id",
                        "canonical_name",
                        "normalized_label",
                        "visible_description",
                        "location_hint",
                        "captured_at_ms",
                        "state",
                    )
                }
                for item in historical
            ],
            "required_json_schema": {
                "cards": [
                    {
                        "candidate_id": "必须来自 candidates",
                        "canonical_name": "物品卡片名称",
                        "normalized_label": "保持候选规范类别",
                        "visible_description": "可见外观或 null",
                        "location_hint": "画面支持的相对位置或 null",
                        "relation_to_wearer": "held|placed_on|visible_at|moved|unknown",
                        "memory_value": "memory_critical|context_only|ignore",
                        "merge_decision": "merge_existing|create_new|uncertain|reject_candidate",
                        "merge_target_observation_id": "历史候选 id 或 null",
                        "semantic_confidence": 0.8,
                        "uncertainty": "不确定点或 null",
                    }
                ],
                "semantic_only_cards": [
                    {
                        "canonical_name": "物品卡片名称",
                        "normalized_label": "稳定英文或中文规范类别",
                        "aliases": ["中英文别名和常见叫法"],
                        "visible_description": "颜色、材质和外观",
                        "location_hint": "画面支持的相对位置或 null",
                        "relation_to_wearer": "held|placed_on|visible_at|moved|unknown",
                        "memory_value": "memory_critical|context_only|ignore",
                        "merge_decision": "merge_existing|create_new|uncertain",
                        "merge_target_observation_id": "历史候选 id 或 null",
                        "semantic_confidence": 0.8,
                        "uncertainty": "不确定点或 null",
                        "supporting_evidence_ids": ["必须来自 available_evidence_ids"],
                    }
                ],
            },
        }
        content: list[dict[str, Any]] = [
            {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)}
        ]
        for image in images[: self.settings.object_card_max_images]:
            data_url = _image_data_url(image.get("uri"))
            if data_url:
                content.append({"type": "image_url", "image_url": {"url": data_url}})
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是独立物品卡片模型，只输出严格 JSON object；只允许 cards 和 semantic_only_cards 两个顶层字段。所有面向用户的名称、描述、位置和不确定性必须使用简体中文。",
                },
                {"role": "user", "content": content},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        token_field = (
            "max_completion_tokens"
            if "xiaomimimo.com" in base_url or model.lower().startswith("mimo-")
            else "max_tokens"
        )
        payload[token_field] = self.settings.object_card_max_tokens
        apply_qwen_request_options(payload, model=model)
        async with httpx.AsyncClient(
            timeout=self.settings.object_card_timeout_seconds,
            trust_env=False,
        ) as client:
            body = await post_chat_completion(
                client,
                url=f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "api-key": api_key,
                    "Content-Type": "application/json",
                },
                payload=payload,
            )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("provider returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content_text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content_text, str):
            raise ValueError("provider returned no JSON text")
        return _parse_json_object(content_text), {"usage": body.get("usage") or {}}


def _aggregate_candidates(
    window_id: str,
    object_perception: dict[str, Any],
    images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    uri_by_id = {
        str(item.get("id")): str(item.get("uri"))
        for item in images
        if item.get("id") and item.get("uri")
    }
    groups: dict[str, dict[str, Any]] = {}
    for frame in object_perception.get("frames") or []:
        if not isinstance(frame, dict) or frame.get("status") != "ready":
            continue
        evidence_id = str(frame.get("evidence_id") or "")
        for detection in frame.get("detections") or []:
            if not isinstance(detection, dict):
                continue
            label = str(detection.get("label") or "").strip()
            if not label:
                continue
            key = label.casefold()
            group = groups.setdefault(
                key,
                {
                    "label": label,
                    "confidence": 0.0,
                    "evidence_ids": [],
                    "evidence_uris": [],
                    "detector_job_ids": [],
                    "bbox_evidence": [],
                    "model_id": frame.get("model_id"),
                    "model_version": frame.get("model_version"),
                    "vocabulary_hash": frame.get("vocabulary_hash"),
                    "late": bool(frame.get("late")),
                },
            )
            group["confidence"] = max(group["confidence"], float(detection.get("confidence") or 0))
            if evidence_id:
                group["evidence_ids"].append(evidence_id)
                if uri_by_id.get(evidence_id):
                    group["evidence_uris"].append(uri_by_id[evidence_id])
            if frame.get("job_id"):
                group["detector_job_ids"].append(str(frame["job_id"]))
            group["bbox_evidence"].append(
                {
                    "evidence_id": evidence_id,
                    "bbox_normalized": detection.get("bbox_normalized"),
                    "confidence": detection.get("confidence"),
                }
            )
    output = []
    for group in groups.values():
        for key in ("evidence_ids", "evidence_uris", "detector_job_ids"):
            group[key] = list(dict.fromkeys(group[key]))
        group["candidate_key"] = "objcandidate:" + hashlib.sha256(
            f"{window_id}\n{group['label']}\n".encode("utf-8")
            + "\n".join(group["evidence_ids"]).encode("utf-8")
        ).hexdigest()[:24]
        output.append(group)
    return sorted(output, key=lambda item: (-item["confidence"], item["label"]))[:20]


def _historical_candidates(
    snapshot: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    labels = {str(item.get("normalized_label") or "") for item in candidates}
    rows = [
        dict(item)
        for item in snapshot.get("object_observations", [])
        if isinstance(item, dict)
        and item.get("state") in {"semantic_only", "fused"}
        and item.get("memory_value") != "ignore"
    ]
    # Same-class detector matches are most useful, but semantic supplements also
    # need recent objects of other classes to decide whether an identity should
    # be merged. Keep the context bounded for latency and prompt stability.
    rows.sort(
        key=lambda item: (
            str(item.get("normalized_label") or "") not in labels,
            -int(item.get("captured_at_ms") or 0),
        )
    )
    return rows[:30]


def _normalize_cards(
    raw: dict[str, Any],
    candidates: list[dict[str, Any]],
    historical: list[dict[str, Any]],
    *,
    available_evidence_ids: list[str],
    allow_partial_candidates: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    unexpected_top_level = sorted(set(raw) - {"cards", "semantic_only_cards"})
    if unexpected_top_level:
        errors.append(
            "unexpected top-level fields: " + ", ".join(unexpected_top_level)
        )
    rows = raw.get("cards", [])
    if not isinstance(rows, list):
        return [], [], [*errors, "cards must be an array"]
    candidates_by_id = {str(item["candidate_id"]): item for item in candidates}
    historical_by_id = {
        str(item.get("observation_id") or item.get("id")): item for item in historical
    }
    cards = []
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"cards[{index}] must be an object")
            continue
        unexpected = sorted(set(row) - _CARD_FIELDS)
        if allow_partial_candidates:
            # Local VLMs sometimes copy semantic-only helper fields onto a
            # detector-backed card. They are ignored here and never persisted.
            unexpected = [
                field
                for field in unexpected
                if field not in {"aliases", "supporting_evidence_ids"}
            ]
        if unexpected:
            errors.append(f"cards[{index}] unexpected fields: {', '.join(unexpected)}")
        candidate_id = str(row.get("candidate_id") or "")
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            # Smaller/local VLMs sometimes faithfully return the detector label
            # but rewrite an opaque objobs ID. Repair only the deterministic
            # case: the supplied normalized label identifies exactly one input
            # candidate that has not already been consumed. Never guess between
            # multiple candidates or use the free-form canonical name.
            supplied_label = str(row.get("normalized_label") or "").strip()
            normalized_supplied, _ = ObjectAliasRegistry.default().normalize(
                supplied_label
            )
            label_matches = [
                item
                for item in candidates
                if str(item.get("normalized_label") or "") == normalized_supplied
                and str(item.get("candidate_id") or "") not in seen
            ]
            if len(label_matches) == 1:
                candidate = label_matches[0]
                candidate_id = str(candidate["candidate_id"])
        if candidate_id in seen and allow_partial_candidates:
            # Exact duplicate output is harmless; keep the first grounded card.
            continue
        if candidate is None and allow_partial_candidates:
            # The corresponding detector observation remains detector_only.
            # Ignoring an ungrounded model row is safer than guessing an ID.
            continue
        if candidate is None or candidate_id in seen:
            errors.append(f"cards[{index}] invalid candidate_id")
            continue
        seen.add(candidate_id)
        decision = str(row.get("merge_decision") or "")
        if decision not in _MERGE_DECISIONS:
            errors.append(f"cards[{index}] invalid merge_decision")
            decision = "uncertain"
        target_id = str(row.get("merge_target_observation_id") or "") or None
        target = historical_by_id.get(target_id or "")
        if decision == "merge_existing":
            if target is None or target.get("normalized_label") != candidate["normalized_label"]:
                errors.append(f"cards[{index}] invalid merge target")
        elif target_id:
            errors.append(f"cards[{index}] merge target only allowed for merge_existing")
        memory_value = str(row.get("memory_value") or "")
        if memory_value not in _MEMORY_VALUES:
            errors.append(f"cards[{index}] invalid memory_value")
            memory_value = "context_only"
        confidence = row.get("semantic_confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            errors.append(f"cards[{index}] invalid semantic_confidence")
            confidence = candidate["confidence"]
        canonical = str(row.get("canonical_name") or "").strip()
        if not canonical:
            errors.append(f"cards[{index}] canonical_name is required")
            canonical = candidate["label"]
        normalized = str(row.get("normalized_label") or "").strip()
        if normalized != candidate["normalized_label"]:
            errors.append(f"cards[{index}] normalized_label must match candidate")
            normalized = candidate["normalized_label"]
        cards.append(
            {
                "candidate_id": candidate_id,
                "canonical_name": canonical[:120],
                "normalized_label": normalized,
                "visible_description": _optional_text(row.get("visible_description"), 400),
                "location_hint": _optional_text(row.get("location_hint"), 240),
                "relation_to_wearer": _optional_text(row.get("relation_to_wearer"), 80) or "unknown",
                "memory_value": memory_value,
                "merge_decision": decision,
                "merge_target_observation_id": target_id,
                "semantic_confidence": float(confidence),
                "uncertainty": _optional_text(row.get("uncertainty"), 300),
            }
        )
    if not allow_partial_candidates and seen != set(candidates_by_id):
        errors.append("cards must contain every candidate exactly once")

    semantic_rows = raw.get("semantic_only_cards", [])
    if not isinstance(semantic_rows, list):
        return cards, [], [*errors, "semantic_only_cards must be an array"]
    if len(semantic_rows) > 5:
        errors.append("semantic_only_cards must contain at most 5 objects")

    registry = ObjectAliasRegistry.default()
    allowed_evidence_ids = set(available_evidence_ids)
    detector_labels = {
        str(item.get("normalized_label") or "").strip().casefold()
        for item in candidates
    }
    semantic_cards: list[dict[str, Any]] = []
    seen_semantic_labels: set[str] = set()
    for index, row in enumerate(semantic_rows[:5]):
        prefix = f"semantic_only_cards[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{prefix} must be an object")
            continue
        unexpected = sorted(set(row) - _SEMANTIC_CARD_FIELDS)
        if unexpected:
            errors.append(f"{prefix} unexpected fields: {', '.join(unexpected)}")

        canonical = str(row.get("canonical_name") or "").strip()
        if not canonical:
            errors.append(f"{prefix} canonical_name is required")
            continue
        supplied_normalized = str(row.get("normalized_label") or canonical).strip()
        normalized, _ = registry.normalize(supplied_normalized)
        if not normalized:
            errors.append(f"{prefix} normalized_label is required")
            continue
        if normalized in detector_labels:
            # The detector-backed card is authoritative for the same class.
            # Treat duplicate semantic output as harmless model redundancy.
            continue
        if normalized in seen_semantic_labels:
            # Keep the first grounded card and do not fail unrelated objects.
            continue

        aliases_value = row.get("aliases")
        if aliases_value is None:
            aliases_value = []
        if not isinstance(aliases_value, list) or any(
            not isinstance(value, str) for value in aliases_value
        ):
            errors.append(f"{prefix} aliases must be an array of strings")
            aliases_value = []
        aliases = list(
            dict.fromkeys(
                text[:120]
                for text in (
                    str(value).strip() for value in [canonical, *aliases_value]
                )
                if text
            )
        )

        evidence_value = row.get("supporting_evidence_ids")
        if not isinstance(evidence_value, list) or not evidence_value:
            if allow_partial_candidates:
                # A semantic-only object has no detector grounding. Never
                # invent an image reference for it; simply discard this
                # ungrounded model suggestion while retaining other cards.
                continue
            errors.append(f"{prefix} requires supporting_evidence_ids")
            evidence_ids: list[str] = []
        else:
            evidence_ids = list(
                dict.fromkeys(str(value) for value in evidence_value if str(value))
            )
            invalid_evidence = sorted(set(evidence_ids) - allowed_evidence_ids)
            if invalid_evidence:
                if allow_partial_candidates:
                    evidence_ids = [
                        evidence_id
                        for evidence_id in evidence_ids
                        if evidence_id in allowed_evidence_ids
                    ]
                    if not evidence_ids:
                        continue
                else:
                    errors.append(f"{prefix} contains unavailable evidence ids")
        seen_semantic_labels.add(normalized)

        decision = str(row.get("merge_decision") or "")
        if decision not in {"merge_existing", "create_new", "uncertain"}:
            errors.append(f"{prefix} invalid merge_decision")
            decision = "uncertain"
        target_id = str(row.get("merge_target_observation_id") or "") or None
        target = historical_by_id.get(target_id or "")
        if decision == "merge_existing":
            if target is None or str(target.get("normalized_label") or "") != normalized:
                errors.append(f"{prefix} invalid merge target")
        elif target_id:
            errors.append(f"{prefix} merge target only allowed for merge_existing")

        memory_value = str(row.get("memory_value") or "")
        if memory_value not in _MEMORY_VALUES:
            errors.append(f"{prefix} invalid memory_value")
            memory_value = "context_only"
        confidence = row.get("semantic_confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            errors.append(f"{prefix} invalid semantic_confidence")
            confidence = 0.0
        semantic_cards.append(
            {
                "canonical_name": canonical[:120],
                "normalized_label": normalized,
                "aliases": aliases,
                "visible_description": _optional_text(
                    row.get("visible_description"), 400
                ),
                "location_hint": _optional_text(row.get("location_hint"), 240),
                "relation_to_wearer": _optional_text(
                    row.get("relation_to_wearer"), 80
                )
                or "unknown",
                "memory_value": memory_value,
                "merge_decision": decision,
                "merge_target_observation_id": target_id,
                "semantic_confidence": float(confidence),
                "uncertainty": _optional_text(row.get("uncertainty"), 300),
                "supporting_evidence_ids": evidence_ids,
            }
        )
    return cards, semantic_cards, errors


def _optional_text(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def _image_data_url(uri: Any) -> str | None:
    if not isinstance(uri, str):
        return None
    parsed = urlparse(uri)
    path = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(uri)
    if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        return None
    media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise ValueError("provider response is not JSON")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("provider response is not a JSON object")
    return value
