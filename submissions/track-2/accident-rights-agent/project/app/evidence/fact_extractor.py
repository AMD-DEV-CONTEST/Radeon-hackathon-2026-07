"""Convert local VLM observations into provenance-bound, unverified facts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.evidence.errors import ModelResponseError
from app.evidence.model_client import LocalVLLMClient, image_data_url, strict_json
from app.schemas.evidence import EvidenceNode, Fact, FactStatus, TimelineEvent


SYSTEM_RULES = """你是交通事故证据观察员，只提取材料中直接可见或直接记载的事实。
禁止判断事故责任、赔偿比例、违法性质、主观故意或不可见的速度。
不能确认的内容必须写入 uncertainty，不得补全、猜测或把常识当成证据。
输出必须是严格 JSON，不要 Markdown。"""
MAX_UNVERIFIED_MODEL_CONFIDENCE = 0.90
MAX_UNCERTAIN_MODEL_CONFIDENCE = 0.70


@dataclass(frozen=True)
class ExtractionResult:
    facts: tuple[Fact, ...]
    timeline_events: tuple[TimelineEvent, ...]
    model: str
    latency_seconds: float
    usage: dict[str, Any]
    raw_response: str


class EvidenceExtractor(Protocol):
    def extract_images(
        self,
        case_id: str,
        nodes_and_paths: list[tuple[EvidenceNode, Path]],
    ) -> ExtractionResult: ...

    def extract_text(
        self, case_id: str, node: EvidenceNode
    ) -> ExtractionResult: ...


class LocalEvidenceExtractor:
    def __init__(self, client: LocalVLLMClient | None = None):
        self.client = client or LocalVLLMClient()

    def extract_images(
        self,
        case_id: str,
        nodes_and_paths: list[tuple[EvidenceNode, Path]],
    ) -> ExtractionResult:
        if not nodes_and_paths:
            raise ValueError("At least one image node is required.")
        if len(nodes_and_paths) > 8:
            raise ValueError("A single local VLM call is limited to eight images.")

        allowed_ids = {node.node_id for node, _ in nodes_and_paths}
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"{SYSTEM_RULES}\n"
                    "每张图片前有其 evidence_node_id。只引用这些 ID。"
                    "输出格式："
                    '{"observations":[{"evidence_node_id":"NODE-...",'
                    '"statement":"完整事实句","subject":"主体",'
                    '"predicate":"单值属性或行为","value":"观测值",'
                    '"confidence":0.0,"uncertainty":"不确定点"}],'
                    '"timeline":[{"label":"可见事件",'
                    '"evidence_node_ids":["NODE-..."],'
                    '"relative_order":1,"confidence":0.0}]}。'
                    "若为连续视频帧，只有在画面直接支持时，标为碰撞前、"
                    "碰撞时或碰撞后；不能判断则写“阶段不确定”。"
                    "若图片本身不足以形成时序，timeline 输出空数组。"
                ),
            }
        ]
        for node, path in nodes_and_paths:
            content.extend(
                [
                    {"type": "text", "text": f"evidence_node_id={node.node_id}"},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url(path)},
                    },
                ]
            )
        call = self.client.chat(
            [{"role": "user", "content": content}],
            max_tokens=1800 if len(nodes_and_paths) > 1 else 900,
        )
        return _validated_result(
            case_id, strict_json(call.content), allowed_ids, call
        )

    def extract_text(self, case_id: str, node: EvidenceNode) -> ExtractionResult:
        if not node.content:
            raise ValueError("Text extraction requires non-empty node content.")
        content = node.content[:16_000]
        prompt = (
            f"{SYSTEM_RULES}\n"
            f"材料 evidence_node_id={node.node_id}。\n"
            "从原文提取时间、地点、人员/车辆、各方陈述、处理结论等明确字段。"
            "输出格式："
            '{"observations":[{"evidence_node_id":"'
            f"{node.node_id}"
            '","statement":"原文事实","subject":"主体",'
            '"predicate":"字段/行为","value":"原文值",'
            '"confidence":0.0,"uncertainty":"不确定点"}],"timeline":[]}。\n'
            f"原文：\n{content}"
        )
        call = self.client.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=1600,
        )
        return _validated_result(
            case_id, strict_json(call.content), {node.node_id}, call
        )


def _validated_result(
    case_id: str,
    payload: dict[str, Any],
    allowed_node_ids: set[str],
    call: Any,
) -> ExtractionResult:
    observations = payload.get("observations")
    timeline = payload.get("timeline", [])
    if not isinstance(observations, list):
        raise ModelResponseError("Model JSON observations must be a list.")
    if not isinstance(timeline, list):
        raise ModelResponseError("Model JSON timeline must be a list.")

    facts: list[Fact] = []
    for item in observations:
        if not isinstance(item, dict):
            raise ModelResponseError("Every observation must be an object.")
        node_id = str(item.get("evidence_node_id", "")).strip()
        if node_id not in allowed_node_ids:
            raise ModelResponseError(
                f"Observation cites unknown evidence node {node_id!r}."
            )
        required = ("statement", "subject", "predicate", "value")
        if any(not str(item.get(field, "")).strip() for field in required):
            raise ModelResponseError(
                f"Observation for {node_id} lacks one of {required}."
            )
        statement = str(item["statement"]).strip()
        subject = str(item["subject"]).strip()
        predicate = str(item["predicate"]).strip()
        value = str(item["value"]).strip()
        uncertainty = str(item.get("uncertainty", "")).strip()
        confidence = min(
            _confidence(item.get("confidence")),
            (
                MAX_UNCERTAIN_MODEL_CONFIDENCE
                if uncertainty
                else MAX_UNVERIFIED_MODEL_CONFIDENCE
            ),
        )
        facts.append(
            Fact(
                fact_id=_stable_id(
                    "FACT", case_id, node_id, subject, predicate, value, statement
                ),
                case_id=case_id,
                statement=statement,
                subject=subject,
                predicate=predicate,
                value=value,
                source_node_ids=(node_id,),
                confidence=confidence,
                status=FactStatus.UNVERIFIED,
                extraction_method="local_vlm",
                model=call.model,
                uncertainty=uncertainty,
            )
        )

    events: list[TimelineEvent] = []
    for position, item in enumerate(timeline, start=1):
        if not isinstance(item, dict) or not str(item.get("label", "")).strip():
            raise ModelResponseError("Every timeline item needs a label.")
        references = item.get("evidence_node_ids")
        if not isinstance(references, list) or not references:
            raise ModelResponseError("Timeline items need evidence_node_ids.")
        node_ids = tuple(str(value) for value in references)
        unknown = set(node_ids) - allowed_node_ids
        if unknown:
            raise ModelResponseError(
                f"Timeline cites unknown evidence nodes: {sorted(unknown)}."
            )
        relative_order = item.get("relative_order", position)
        if not isinstance(relative_order, int):
            relative_order = position
        label = str(item["label"]).strip()
        events.append(
            TimelineEvent(
                event_id=_stable_id(
                    "EVENT", case_id, label, *sorted(node_ids)
                ),
                case_id=case_id,
                label=label,
                relative_order=max(1, relative_order),
                source_node_ids=node_ids,
                confidence=min(
                    _confidence(item.get("confidence")),
                    MAX_UNVERIFIED_MODEL_CONFIDENCE,
                ),
            )
        )

    return ExtractionResult(
        facts=tuple(facts),
        timeline_events=tuple(events),
        model=call.model,
        latency_seconds=call.latency_seconds,
        usage=call.usage,
        raw_response=call.content,
    )


def _confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.5
    return round(min(1.0, max(0.0, parsed)), 4)


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:16].upper()}"
