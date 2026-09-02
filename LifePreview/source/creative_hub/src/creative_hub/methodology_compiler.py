"""Structured methodology selection and GLM direction compilation.

This module is intentionally model-neutral at the rule layer.  Seedance-only
cards are selected only when the target family is Seedance; Qwen image and Wan
video compilation receive the universal directing rules plus their own
versioned capability profile.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

from pydantic import ValidationError
from shared_contracts import (
    AUTHORITY_TIER_ORDER,
    CapabilityProfileV1,
    CompiledPromptBundleV1,
    CompiledPromptV1,
    DirectionContractV1,
    MethodologyBriefV1,
    MethodologyStage,
    OmittedRuleV1,
    PromptModality,
    RuleCardV1,
    SelectedRuleV1,
)

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.models import MethodologySnapshotRecord


GLM_DIRECTION_URL = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
GLM_DIRECTION_MODEL = "glm-5.1"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_SOURCE_CHARACTERS = 24_000

# Precise glyphs and commercial marks are compositing concerns, not reliable
# generative-model output.  Keep this as a versioned adapter capability guard
# so rule cards remain reusable methodology instead of accumulating provider-
# specific prompt folklore.
RENDER_SAFE_ADAPTER_GUARD = (
    "模型能力边界：画面仅保留无字、无品牌、可替换的清晰占位区；"
    "准确文字、数字、品牌名和标志交由后期图层，不要求生成模型绘制。"
)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


DirectionTransport = Callable[
    [str, dict[str, str], dict[str, Any], float], tuple[int, bytes]
]


def _http_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[int, bytes]:
    request = Request(
        url,
        method="POST",
        headers=headers,
        data=json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"),
    )
    try:
        opener = build_opener(_RejectRedirects())
        with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310
            return int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        try:
            return int(exc.code), b""
        finally:
            exc.close()


class MethodologyCompilationError(RuntimeError):
    """A methodology-aware compilation could not produce a valid contract."""


def build_capability_profile(
    *,
    profile_key: str,
    target_model_family: str,
    modality: PromptModality,
    supported_modes: Sequence[str],
    supported_features: Sequence[str],
    forbidden_features: Sequence[str],
    max_prompt_characters: int,
) -> CapabilityProfileV1:
    identity = {
        "schema_version": "capability-profile.v1",
        "profile_key": profile_key,
        "target_model_family": target_model_family,
        "modality": modality.value,
        "supported_modes": list(supported_modes),
        "supported_features": list(supported_features),
        "forbidden_features": list(forbidden_features),
        "max_prompt_characters": max_prompt_characters,
    }
    return CapabilityProfileV1(
        **identity,
        digest=canonical_json_digest(identity),
    )


QWEN_IMAGE_CAPABILITY = build_capability_profile(
    profile_key="qwen-image.v2",
    target_model_family="qwen-image",
    modality=PromptModality.IMAGE,
    supported_modes=("t2i", "reference-image"),
    supported_features=("positive-prompt", "negative-prompt", "reference-duty"),
    forbidden_features=(
        "camera-motion",
        "native-audio",
        "dialogue-timing",
        "model-rendered-readable-text",
        "brand-logo-rendering",
    ),
    max_prompt_characters=4_000,
)

WAN_VIDEO_CAPABILITY = build_capability_profile(
    profile_key="wan2.2.v2",
    target_model_family="wan2.2",
    modality=PromptModality.VIDEO,
    supported_modes=("t2v", "i2v", "first_last_frame"),
    supported_features=(
        "action-chain",
        "camera-motion",
        "first-last-frame",
        "continuity-locks",
    ),
    forbidden_features=(
        "seedance-reference-tags",
        "seedance-native-extend",
        "model-rendered-readable-text",
        "brand-logo-rendering",
    ),
    max_prompt_characters=6_000,
)


def _matches(allowed: Sequence[str], actual: str | None) -> bool:
    return not allowed or (actual is not None and actual in allowed)


def build_methodology_brief(
    *,
    snapshot: MethodologySnapshotRecord,
    project_type: str,
    stage: MethodologyStage,
    operation: str,
    capability_profile: CapabilityProfileV1,
    mode: str | None = None,
    max_methodology_characters: int = 12_000,
) -> MethodologyBriefV1:
    """Deterministically filter and compress frozen rules for one operation."""

    candidates: list[tuple[int, int, int, SelectedRuleV1]] = []
    omitted: list[OmittedRuleV1] = []
    tier_order = {tier: index for index, tier in enumerate(AUTHORITY_TIER_ORDER)}
    for card_order, item in enumerate(snapshot.ordered_cards):
        try:
            revision_id = UUID(str(item["skill_revision_id"]))
            skill_key = str(item["skill_key"])
            card = RuleCardV1.model_validate(item["card"])
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise MethodologyCompilationError(
                "frozen methodology snapshot contains an invalid rule card"
            ) from exc
        applicability = card.applicability
        mismatch: str | None = None
        if not _matches(applicability.project_types, project_type):
            mismatch = f"project type {project_type!r} is outside applicability"
        elif stage not in applicability.stages:
            mismatch = f"stage {stage.value!r} is outside applicability"
        elif not _matches(applicability.operations, operation):
            mismatch = f"operation {operation!r} is outside applicability"
        elif not _matches(
            applicability.target_model_families,
            capability_profile.target_model_family,
        ):
            mismatch = (
                f"target {capability_profile.target_model_family!r} is outside "
                "applicability"
            )
        elif not _matches(applicability.modes, mode):
            mismatch = f"mode {mode!r} is outside applicability"

        for clause_order, clause in enumerate(card.clauses):
            if mismatch is not None:
                omitted.append(
                    OmittedRuleV1(
                        skill_revision_id=revision_id,
                        rule_id=clause.rule_id,
                        reason=mismatch,
                    )
                )
                continue
            selected = SelectedRuleV1(
                skill_revision_id=revision_id,
                skill_key=skill_key,
                rule_id=clause.rule_id,
                authority_tier=clause.authority_tier,
                directive=clause.directive,
                required_outputs=clause.required_outputs,
                forbidden=clause.forbidden,
                compression_priority=clause.compression_priority,
            )
            candidates.append(
                (
                    tier_order[clause.authority_tier],
                    -clause.compression_priority,
                    card_order * 10_000 + clause_order,
                    selected,
                )
            )

    candidates.sort(key=lambda item: item[:3])
    selected_rules: list[SelectedRuleV1] = []
    used_characters = 0
    for _tier, _priority, _order, rule in candidates:
        rule_characters = len(rule.directive) + sum(
            len(value) for value in (*rule.required_outputs, *rule.forbidden)
        )
        if used_characters + rule_characters > max_methodology_characters:
            omitted.append(
                OmittedRuleV1(
                    skill_revision_id=rule.skill_revision_id,
                    rule_id=rule.rule_id,
                    reason="methodology character budget exhausted",
                )
            )
            continue
        selected_rules.append(rule)
        used_characters += rule_characters

    return MethodologyBriefV1(
        snapshot_id=snapshot.id,
        snapshot_digest=snapshot.digest,
        project_type=project_type,
        stage=stage,
        operation=operation,
        target_model_family=capability_profile.target_model_family,
        mode=mode,
        selected_rules=tuple(selected_rules),
        omitted_rules=tuple(omitted),
        capability_profile=capability_profile,
        max_methodology_characters=max_methodology_characters,
    )


def _json_object(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    elif text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
    try:
        result = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise MethodologyCompilationError(
            "GLM methodology compiler returned invalid JSON"
        ) from None
    if not isinstance(result, dict):
        raise MethodologyCompilationError(
            "GLM methodology compiler returned a non-object"
        )
    return result


@dataclass(frozen=True, slots=True)
class GlmDirectionCompiler:
    _transport: DirectionTransport = _http_transport
    _timeout_seconds: float = 240.0
    model_name: str = GLM_DIRECTION_MODEL
    model_version: str = "glm-5.1"

    def compile_sequence(
        self,
        *,
        api_key: str,
        methodology_brief: MethodologyBriefV1,
        adapter_methodology_briefs: Sequence[MethodologyBriefV1] = (),
        source_context: Mapping[str, Any],
        minimum_contracts: int = 1,
        maximum_contracts: int = 16,
    ) -> tuple[DirectionContractV1, ...]:
        if not methodology_brief.selected_rules:
            raise MethodologyCompilationError(
                "no executable methodology rules apply to this operation"
            )
        source_json = json.dumps(
            dict(source_context), ensure_ascii=False, separators=(",", ":")
        )
        if len(source_json) > MAX_SOURCE_CHARACTERS:
            raise MethodologyCompilationError(
                "source context exceeds the methodology compiler limit"
            )
        system_content = (
            "你是创作方法论编译器，不是自由续写模型。先内化下列有序结构化规则和"
            "目标模型能力，再把来源材料转换为 DirectionContractV1。严格遵守 authority_tier，"
            "不得把 forbidden_features 写入合同，不得声称观察了未提供的素材。每个镜头只能"
            "承担一个 narrative_job，action_chain 必须按初态、触发、决定性变化、反应、"
            "跟随动作、局部终点展开；镜头、表演、光线、声音必须服务 felt_intent。只输出"
            "JSON 对象 {\"contracts\":[...]}，字段必须完全符合 DirectionContractV1；"
            "不要输出最终 Qwen/Wan 提示词、Markdown 或解释。\n"
            "METHODOLOGY_BRIEF_V1="
            + methodology_brief.model_dump_json()
            + "\nADAPTER_METHODOLOGY_BRIEFS_V1="
            + json.dumps(
                [
                    item.model_dump(mode="json")
                    for item in adapter_methodology_briefs
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\nDIRECTION_CONTRACT_V1_JSON_SCHEMA="
            + json.dumps(
                DirectionContractV1.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"SOURCE_CONTEXT={source_json}"},
        ]
        last_error: MethodologyCompilationError | None = None
        for attempt in range(2):
            content = ""
            payload = {
                "model": self.model_name,
                "messages": messages,
                "thinking": {"type": "disabled"},
                "stream": False,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
            try:
                status_code, raw = self._transport(
                    GLM_DIRECTION_URL,
                    {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    payload,
                    self._timeout_seconds,
                )
            except (TimeoutError, URLError, OSError):
                raise MethodologyCompilationError(
                    "GLM methodology compiler is temporarily unavailable"
                ) from None
            if not 200 <= status_code < 300:
                raise MethodologyCompilationError(
                    "GLM methodology compiler request failed"
                )
            if len(raw) > MAX_RESPONSE_BYTES:
                raise MethodologyCompilationError(
                    "GLM methodology compiler response is too large"
                )
            try:
                response = json.loads(raw.decode("utf-8"))
                content = response["choices"][0]["message"]["content"]
                values = _json_object(content).get("contracts")
                if not isinstance(values, list):
                    raise MethodologyCompilationError(
                        "GLM methodology compiler omitted contracts"
                    )
                if not minimum_contracts <= len(values) <= maximum_contracts:
                    raise MethodologyCompilationError(
                        "GLM methodology compiler returned an invalid contract count"
                    )
                contracts = tuple(
                    DirectionContractV1.model_validate(value) for value in values
                )
                primary_rule_ids = {
                    rule.rule_id for rule in methodology_brief.selected_rules
                }
                allowed_rule_ids = primary_rule_ids | {
                    rule.rule_id
                    for brief in adapter_methodology_briefs
                    for rule in brief.selected_rules
                }
                for contract in contracts:
                    if not set(contract.applied_rule_ids) <= allowed_rule_ids:
                        raise MethodologyCompilationError(
                            "direction contract cites rules outside the frozen brief"
                        )
                    if not set(contract.applied_rule_ids) & primary_rule_ids:
                        raise MethodologyCompilationError(
                            "direction contract cites no primary directing rule"
                        )
                return contracts
            except (
                KeyError,
                IndexError,
                TypeError,
                UnicodeError,
                json.JSONDecodeError,
                ValidationError,
                MethodologyCompilationError,
            ) as exc:
                last_error = MethodologyCompilationError(
                    "GLM methodology compiler returned an invalid contract"
                )
                if attempt == 0:
                    messages.extend(
                        (
                            {"role": "assistant", "content": str(content)[:12_000]},
                            {
                                "role": "user",
                                "content": (
                                    "上一个 JSON 未通过 DirectionContractV1 严格校验。"
                                    "只修复结构、缺失字段、规则引用和冲突；不要改变来源事实，"
                                    "重新输出完整 {\"contracts\":[...]}。"
                                ),
                            },
                        )
                    )
                    continue
                raise last_error from exc
        assert last_error is not None
        raise last_error


def _reference_text(contract: DirectionContractV1) -> str:
    duties = []
    for duty in contract.reference_duties:
        duties.append(
            f"{duty.asset_ref} 仅负责 {', '.join(duty.owns_dimensions)}；"
            f"保持 {', '.join(duty.must_preserve) or '指定维度'}；"
            f"不得迁移 {', '.join(duty.must_not_transfer) or '未授权维度'}"
        )
    return "；".join(duties)


def compile_qwen_image_bundle(
    *,
    compilation_id: UUID,
    snapshot: MethodologySnapshotRecord,
    contract: DirectionContractV1,
    omitted_rules: Sequence[OmittedRuleV1] = (),
    additional_rule_ids: Sequence[str] = (),
    applied_rule_ids: Sequence[str] | None = None,
) -> CompiledPromptBundleV1:
    """Compile distinct first/last still prompts without video/audio leakage."""

    common = "；".join(
        (
            f"静态构图视角：{contract.point_of_view}",
            *contract.composition,
            f"角色可见情绪：{contract.felt_intent}",
            *contract.lighting,
            *contract.continuity_locks,
        )
    )
    references = _reference_text(contract)
    first = "；".join(
        value
        for value in (
            common,
            f"画面初态：{contract.action_chain.initial_state}",
            f"情绪意图：{contract.felt_intent}",
            references,
            RENDER_SAFE_ADAPTER_GUARD,
        )
        if value
    )
    last = "；".join(
        value
        for value in (
            common,
            f"画面终态：{contract.action_chain.local_endpoint}",
            f"戏剧转折：{contract.dramatic_turn}",
            references,
            RENDER_SAFE_ADAPTER_GUARD,
        )
        if value
    )
    prompt_values = (
        CompiledPromptV1(role="first-frame", text=first),
        CompiledPromptV1(role="last-frame", text=last),
    )
    effective_rule_ids = tuple(
        dict.fromkeys(
            (
                *(
                    contract.applied_rule_ids
                    if applied_rule_ids is None
                    else applied_rule_ids
                ),
                *additional_rule_ids,
            )
        )
    )
    base = {
        "schema_version": "compiled-prompt-bundle.v1",
        "compilation_id": str(compilation_id),
        "methodology_snapshot_id": str(snapshot.id),
        "methodology_snapshot_digest": snapshot.digest,
        "direction_contract_digest": canonical_json_digest(
            contract.model_dump(mode="json")
        ),
        "adapter_key": "qwen-image",
        "adapter_version": "qwen-image.v2",
        "target_model_family": "qwen-image",
        "modality": "image",
        "prompts": [item.model_dump(mode="json") for item in prompt_values],
        "parameters": {},
        "applied_rule_ids": list(effective_rule_ids),
        "omitted_rules": [item.model_dump(mode="json") for item in omitted_rules],
    }
    return CompiledPromptBundleV1(
        **base,
        bundle_digest=canonical_json_digest(base),
    )


def compile_wan_video_bundle(
    *,
    compilation_id: UUID,
    snapshot: MethodologySnapshotRecord,
    contract: DirectionContractV1,
    mode: str,
    omitted_rules: Sequence[OmittedRuleV1] = (),
    applied_rule_ids: Sequence[str] | None = None,
) -> CompiledPromptBundleV1:
    """Compile Wan prompt prose from the reusable direction contract."""

    chain = contract.action_chain
    prompt = "\n".join(
        (
            f"叙事任务：{contract.narrative_job}",
            f"情绪意图：{contract.felt_intent}；主要生成预算：{contract.primary_spend}",
            (
                "动作链："
                f"初态 {chain.initial_state}；触发 {chain.trigger}；"
                f"决定性变化 {chain.decisive_change}；反应 {chain.response}；"
                f"跟随动作 {chain.follow_through}；局部终点 {chain.local_endpoint}。"
            ),
            f"镜头覆盖：{'；'.join(chain.camera_coverage)}；{'；'.join(contract.camera)}",
            f"构图：{'；'.join(contract.composition)}",
            f"表演：{'；'.join(contract.performance)}",
            f"光线：{'；'.join(contract.lighting)}",
            f"声音：{'；'.join(contract.sound) or '无原生声音要求'}",
            f"连续性锁：{'；'.join(contract.continuity_locks) or '保持已确认状态'}",
            f"已完成情节不得重演：{'；'.join(contract.completed_beats) or '无'}",
            f"保留情节不得提前出现：{'；'.join(contract.reserved_beats) or '无'}",
            f"参考职责：{_reference_text(contract) or '无外部参考'}",
            RENDER_SAFE_ADAPTER_GUARD,
        )
    )
    prompt_value = CompiledPromptV1(role="video", text=prompt)
    base = {
        "schema_version": "compiled-prompt-bundle.v1",
        "compilation_id": str(compilation_id),
        "methodology_snapshot_id": str(snapshot.id),
        "methodology_snapshot_digest": snapshot.digest,
        "direction_contract_digest": canonical_json_digest(
            contract.model_dump(mode="json")
        ),
        "adapter_key": "wan2.2",
        "adapter_version": "wan2.2.v2",
        "target_model_family": "wan2.2",
        "modality": "video",
        "prompts": [prompt_value.model_dump(mode="json")],
        "parameters": {"generation_mode": mode},
        "applied_rule_ids": list(
            contract.applied_rule_ids
            if applied_rule_ids is None
            else applied_rule_ids
        ),
        "omitted_rules": [item.model_dump(mode="json") for item in omitted_rules],
    }
    return CompiledPromptBundleV1(
        **base,
        bundle_digest=canonical_json_digest(base),
    )


def new_compilation_id() -> UUID:
    return uuid4()


__all__ = [
    "GLM_DIRECTION_MODEL",
    "GLM_DIRECTION_URL",
    "GlmDirectionCompiler",
    "MethodologyCompilationError",
    "QWEN_IMAGE_CAPABILITY",
    "WAN_VIDEO_CAPABILITY",
    "build_capability_profile",
    "build_methodology_brief",
    "compile_qwen_image_bundle",
    "compile_wan_video_bundle",
    "new_compilation_id",
]
