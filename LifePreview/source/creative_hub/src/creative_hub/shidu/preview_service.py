"""Read-only director preview projected only from frozen Shidu revisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from creative_hub.shidu.repository import ShiduRepository


_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


@dataclass(frozen=True)
class PreviewShot:
    ordinal: int
    narrative_task: str
    action: str
    state_transition: str
    duration_seconds: int


@dataclass(frozen=True)
class PreviewSourceSummary:
    registered_domain: str
    source_type: str
    canonical_url: str


@dataclass(frozen=True)
class DirectorPreview:
    script_revision_id: UUID
    script_digest: str
    methodology_revision_id: UUID
    methodology_version: str
    direction_revision_id: UUID
    direction_digest: str
    evidence_pack_revision_id: UUID
    provisional_title: str
    experience_promise: str
    opening_line: str
    opening_line_kind: str
    opening_line_label: str
    content_mode: str
    content_label: str
    content_notice: str
    emotion_curve: tuple[str, ...]
    shots: tuple[PreviewShot, ...]
    duration_estimate_seconds: int
    narration_chinese_character_count: int
    fit_for: tuple[str, ...]
    not_fit_for: tuple[str, ...]
    source_summaries: tuple[PreviewSourceSummary, ...]
    spoiler_level: str
    risk_flags: tuple[str, ...]


class PreviewService:
    """Has no transport/provider dependency and performs projection-only reads."""

    def __init__(self, repository: ShiduRepository) -> None:
        self._repository = repository

    def build(self, script_revision_id: UUID) -> DirectorPreview:
        script, methodology, direction, pack, claims, sources = (
            self._repository.load_trial_script_context(script_revision_id)
        )
        payload = script.payload
        shots = tuple(
            PreviewShot(
                ordinal=int(item["ordinal"]),
                narrative_task=str(item["narrative_task"]),
                action=str(item["action"]),
                state_transition=(
                    f"{item['state_before']}→{item['state_after']}"
                ),
                duration_seconds=int(item["duration_seconds"]),
            )
            for item in payload["shots"]
        )
        referenced_claim_ids = {
            UUID(str(item)) for item in direction.payload["evidence_ids"]
        }
        referenced_source_ids = {
            claim.source_document_revision_id
            for claim in claims
            if claim.id in referenced_claim_ids
        }
        source_summaries = tuple(
            PreviewSourceSummary(
                registered_domain=item.registered_domain,
                source_type=item.source_type,
                canonical_url=item.canonical_url,
            )
            for item in sorted(
                (
                    value
                    for value in sources
                    if value.id in referenced_source_ids
                    and value.source_type != "ai_generated"
                ),
                key=lambda value: (
                    value.registered_domain,
                    value.source_type,
                    value.canonical_url,
                ),
            )
        )
        opening_kind = str(payload["opening_line_kind"])
        content_mode = str(
            pack.coverage.get("content_mode", "source_grounded")
        )
        ai_completed = content_mode == "ai_completed"
        return DirectorPreview(
            script_revision_id=script.id,
            script_digest=script.digest,
            methodology_revision_id=methodology.id,
            methodology_version=methodology.methodology_version,
            direction_revision_id=direction.id,
            direction_digest=direction.digest,
            evidence_pack_revision_id=pack.id,
            provisional_title=str(payload["provisional_title"]),
            experience_promise=str(payload["experience_promise"]),
            opening_line=str(payload["opening_line"]),
            opening_line_kind=opening_kind,
            opening_line_label=(
                "原著核验引语"
                if opening_kind == "verified_quote"
                else "AI 改写开场"
            ),
            content_mode=content_mode,
            content_label=(
                "AI 补全剧情（非原文）"
                if ai_completed
                else "原文与资料核验改写"
            ),
            content_notice=(
                "未找到可核验原文；内容由 AI 根据书目信息及可用第三方资料补全，可能存在偏差。"
                if ai_completed
                else "内容根据已核验原文与资料进行改写。"
            ),
            emotion_curve=tuple(str(item) for item in payload["emotion_curve"]),
            shots=shots,
            duration_estimate_seconds=sum(
                item.duration_seconds for item in shots
            ),
            narration_chinese_character_count=len(
                _HAN_RE.findall(str(payload["narration_text"]))
            ),
            fit_for=tuple(
                str(item["text"]) for item in payload["fit_for"]
            ),
            not_fit_for=tuple(
                str(item["text"]) for item in payload["not_fit_for"]
            ),
            source_summaries=source_summaries,
            spoiler_level=str(payload["spoiler_level"]),
            risk_flags=tuple(
                key
                for key, flagged in sorted(payload["risk_flags"].items())
                if flagged
            ),
        )


__all__ = [
    "DirectorPreview",
    "PreviewService",
    "PreviewShot",
    "PreviewSourceSummary",
]
