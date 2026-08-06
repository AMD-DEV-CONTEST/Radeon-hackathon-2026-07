"""Two-stage, evidence-bound compiler for immutable Shidu trial scripts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from uuid import UUID

from creative_hub.shidu.repository import IdempotencyConflict, ShiduRepository
from creative_hub.shidu.safety_cards import BookSafetyCategory
from creative_hub.shidu.schemas import (
    StoreTrialScript,
    TrialScriptRevision,
)
from creative_hub.shidu.trial_methodology import (
    SHOT_BEATS,
    TRIAL_SCRIPT_SCHEMA_VERSION,
    TRIAL_VALIDATOR_VERSION,
)
from creative_hub.shidu.trial_safety import (
    TrialSafetyGateService,
    TrialScriptSafety,
)
from creative_hub.shidu.trial_script_validator import (
    TRIAL_COMPILER_VERSION,
    TrialScriptValidator,
    action_skeleton_digest,
    parse_action_skeleton,
    parse_narration,
)


@dataclass(frozen=True)
class TrialEvidenceInput:
    evidence_id: UUID
    claim_type: str
    normalized_claim: str
    spoiler_level: str


@dataclass(frozen=True)
class ActionSkeletonRequest:
    evidence_pack_revision_id: UUID
    evidence_pack_digest: str
    direction_revision_id: UUID
    direction_digest: str
    methodology_revision_id: UUID
    methodology_digest: str
    methodology_payload: dict
    direction_payload: dict
    claims: tuple[TrialEvidenceInput, ...]
    model_version: str
    prompt_version: str
    primary_safety_category: str
    safety_cards_manifest_digest: str
    pre_safety_decision_digest: str
    tools_allowed: bool = False


@dataclass(frozen=True)
class NarrationRequest:
    evidence_pack_revision_id: UUID
    direction_revision_id: UUID
    methodology_revision_id: UUID
    action_skeleton: dict
    action_skeleton_digest: str
    claims: tuple[TrialEvidenceInput, ...]
    model_version: str
    prompt_version: str
    primary_safety_category: str
    safety_cards_manifest_digest: str
    pre_safety_decision_digest: str
    tools_allowed: bool = False


class TrialScriptSafetyBlocked(ValueError):
    """Trusted pre-compile safety policy forbids creative generation."""


class TrialScriptTransport(Protocol):
    def generate_action_skeleton(self, request: ActionSkeletonRequest) -> object: ...

    def generate_narration(self, request: NarrationRequest) -> object: ...


class DeterministicTrialScriptTransport:
    """Offline fallback; generation remains data-only and application-scoped."""

    @staticmethod
    def _evidence(request: ActionSkeletonRequest | NarrationRequest) -> tuple[UUID, UUID]:
        factual = next(
            (
                item.evidence_id
                for item in request.claims
                if item.claim_type in {"plot_node", "factual_context"}
            ),
            request.claims[0].evidence_id,
        )
        style = next(
            (
                item.evidence_id
                for item in request.claims
                if item.claim_type
                in {"emotional_reaction", "style_judgement", "reader_fit"}
            ),
            request.claims[0].evidence_id,
        )
        return factual, style

    def generate_action_skeleton(self, request: ActionSkeletonRequest) -> object:
        factual, style = self._evidence(request)
        durations = (7, 9, 10, 10, 10, 8)
        actions = (
            "我在冷雨里推门进入骤然安静的房间，雨水沿袖口滴在地板上。",
            "我在冷雨声里把攥紧的钥匙摊在掌心，确认自己只想守住眼前的选择。",
            "门外的脚步逼近，我把退路挡住，听见呼吸越来越急。",
            "我把钥匙放上桌面，伸手推开那扇一直不敢碰的门。",
            "冷雨敲窗，门轴响起，我看见眼前的关系已经因为这个动作发生变化。",
            "我停在冷雨后的门槛上，没有替下一步作答，只握紧仍然发冷的手。",
        )
        shots = []
        for beat, duration, action in zip(SHOT_BEATS, durations, actions, strict=True):
            before, after = str(beat["required_change"]).split("→", 1)
            shots.append(
                {
                    "ordinal": beat["ordinal"],
                    "narrative_task": beat["narrative_task"],
                    "action": action,
                    "composition": "第一人称近景，主体动作清晰",
                    "camera_movement": "克制缓慢推进",
                    "lighting": "冷雨环境光与室内暖光交界",
                    "sound": "雨声、呼吸与物件触碰声",
                    "duration_seconds": duration,
                    "state_before": before,
                    "state_after": after,
                    "factual_evidence_ids": [str(factual)],
                    "style_evidence_ids": [str(style)],
                }
            )
        title = str(request.direction_payload.get("title") or "门槛上的一刻")
        return {
            "provisional_title": title,
            "experience_promise": "借我的眼睛，停在一次必须付出代价的选择前。",
            "narrator": "书中此刻的第一人称主人公",
            "continuous_moment": "冷雨夜里，我从推门到停在门槛上的连续片刻",
            "primary_conflict": "我必须在退回安全处与承担眼前代价之间选择",
            "known_now": ["门外有人逼近", "钥匙握在我手里", "选择会立刻付出代价"],
            "unknown_now": ["门后决定的长期后果", "其他人尚未说出的答案"],
            "emotion_curve": ["警觉", "渴望", "受压", "决断", "震动", "悬停"],
            "shots": shots,
        }

    def generate_narration(self, request: NarrationRequest) -> object:
        factual, style = self._evidence(request)
        texts = (
            "我推开门时，冷雨顺着袖口钻进来，屋里的安静像一根绷紧的线，我知道今晚已经不同。",
            "我在冷雨声里把钥匙摊在掌心，看清自己真正想守住的不是这扇门，而是仍能亲手选择的余地。",
            "我听见冷雨和脚步一寸寸逼近，退路就在身后，可我的手没有松开，连呼吸都被门缝里的风压低。",
            "我把钥匙放上桌面，木头发出很轻的一声，我终于越过犹豫，准备推开那道冰凉的门。",
            "我用力推开门，门轴的响声划开沉默，眼前的人停住了，我也明白这个动作已经收不回来。",
            "我站在冷雨后的门槛上，掌心已经空了；下一步没有答案，只剩那扇打开的门等我迈过去。",
        )
        return {
            "opening_line": "我推开门时，冷雨顺着袖口钻进来",
            "narration_cues": [
                {
                    "cue_key": f"narration-{index}",
                    "shot_ordinal": index,
                    "text": text,
                    "pause_after_ms": 300 if index < 6 else 700,
                    "factual_evidence_ids": [str(factual)],
                    "style_evidence_ids": [str(style)],
                }
                for index, text in enumerate(texts, start=1)
            ],
            "pronunciation_dictionary": {},
        }


class AICompletedTrialScriptTransport:
    """Deterministically adapt explicitly disclosed AI-completed claims."""

    @staticmethod
    def _evidence(
        request: ActionSkeletonRequest | NarrationRequest,
    ) -> tuple[TrialEvidenceInput, TrialEvidenceInput]:
        factual = next(
            item
            for item in request.claims
            if item.claim_type in {"plot_node", "factual_context"}
        )
        style = next(
            item
            for item in request.claims
            if item.claim_type
            in {"emotional_reaction", "style_judgement", "reader_fit"}
        )
        return factual, style

    @staticmethod
    def _anchor(claim: TrialEvidenceInput, limit: int) -> str:
        value = " ".join(claim.normalized_claim.split())
        return value[:limit].rstrip("，。；：,. ")

    @staticmethod
    def _fragment(value: str, limit: int = 12) -> str:
        fragment = "".join(
            character
            for character in value
            if "\u3400" <= character <= "\u9fff"
        )[:limit]
        return fragment or "人物正在作出选择"

    def generate_action_skeleton(self, request: ActionSkeletonRequest) -> object:
        factual, style = self._evidence(request)
        anchor = self._anchor(factual, 180)
        style_anchor = self._anchor(style, 100)
        fragment = self._fragment(anchor)
        durations = (7, 9, 10, 10, 10, 8)
        phases = (
            "我先停住，辨认眼前发生的变化",
            "我把注意力放回人物正在面对的选择",
            "我感到压力靠近，却不替未知部分作答",
            "我顺着已经给出的线索迈出一步",
            "我看见这个动作带来的即时变化",
            "我停在这一刻，不补写它之后的答案",
        )
        shots = []
        for beat, duration, phase in zip(SHOT_BEATS, durations, phases, strict=True):
            before, after = str(beat["required_change"]).split("→", 1)
            shots.append(
                {
                    "ordinal": beat["ordinal"],
                    "narrative_task": beat["narrative_task"],
                    "action": f"{phase}。画面围绕“{fragment}”展开。",
                    "composition": "第一人称近景，动作与环境变化清晰",
                    "camera_movement": "克制缓慢推进",
                    "lighting": "柔和环境光突出人物状态变化",
                    "sound": "呼吸、脚步与环境底噪",
                    "duration_seconds": duration,
                    "state_before": before,
                    "state_after": after,
                    "factual_evidence_ids": [str(factual.evidence_id)],
                    "style_evidence_ids": [str(style.evidence_id)],
                }
            )
        title = str(request.direction_payload.get("title") or "这一刻的选择")
        return {
            "provisional_title": title[:120],
            "experience_promise": "以第一人称进入一个由 AI 明确补全、并保留不确定性的阅读时刻。",
            "narrator": "AI 补全内容中的第一人称人物",
            "continuous_moment": f"我在同一场景里围绕“{fragment}”从观察走向行动",
            "primary_conflict": f"我必须面对“{fragment}”呈现的当下选择",
            "known_now": [fragment, self._fragment(style_anchor)],
            "unknown_now": ["这段 AI 补全之外尚未核验的细节"],
            "emotion_curve": ["观察", "迟疑", "受压", "选择", "震动", "悬停"],
            "shots": shots,
        }

    def generate_narration(self, request: NarrationRequest) -> object:
        factual, style = self._evidence(request)
        anchor = self._anchor(factual, 180)
        fragment = self._fragment(anchor)
        phases = (
            "我先看清眼前这一刻",
            "我把注意力放回这个选择",
            "我感到压力正在靠近",
            "我决定顺着已有线索行动",
            "我看见状态发生即时变化",
            "我停在这里，不替未知部分作答",
        )
        texts = [
            f"{phase}。{fragment}。我不把补全当原文。"
            for phase in phases
        ]
        while sum(
            "\u3400" <= character <= "\u9fff"
            for text in texts
            for character in text
        ) < 180:
            texts[-1] += "我仍停在此刻。"
        return {
            "opening_line": texts[0],
            "narration_cues": [
                {
                    "cue_key": f"ai-completion-{index}",
                    "shot_ordinal": index,
                    "text": text,
                    "pause_after_ms": 300 if index < 6 else 700,
                    "factual_evidence_ids": [str(factual.evidence_id)],
                    "style_evidence_ids": [str(style.evidence_id)],
                }
                for index, text in enumerate(texts, start=1)
            ],
            "pronunciation_dictionary": {},
        }


class TrialScriptCompiler:
    def __init__(
        self,
        *,
        repository: ShiduRepository,
        transport: TrialScriptTransport | None = None,
        model_version: str = "application-owned-deterministic-v1",
        prompt_version: str = "shidu-trial-prompt-v1",
    ) -> None:
        if not model_version or len(model_version) > 160:
            raise ValueError("model_version is invalid")
        if not prompt_version or len(prompt_version) > 160:
            raise ValueError("prompt_version is invalid")
        self._repository = repository
        self._transport = transport or DeterministicTrialScriptTransport()
        self._model_version = model_version
        self._prompt_version = prompt_version

    def compile(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        methodology_revision_id: UUID,
        command_key: str,
        spoiler_policy: str = "light",
        opening_line_kind: str = "ai_adapted",
        verified_quote_evidence_id: UUID | None = None,
        book_category: BookSafetyCategory | str = BookSafetyCategory.FICTION,
    ) -> TrialScriptRevision:
        try:
            resolved_category = BookSafetyCategory(book_category)
        except (TypeError, ValueError) as exc:
            raise TrialScriptSafetyBlocked(
                "book safety category is invalid"
            ) from exc
        replay = self._repository.get_trial_script_for_command(
            project_id, command_key
        )
        if replay is not None:
            requested_quote_evidence_id = (
                str(verified_quote_evidence_id)
                if verified_quote_evidence_id is not None
                else None
            )
            if (
                replay.book_id != book_id
                or replay.resonance_direction_revision_id != direction_revision_id
                or replay.methodology_revision_id != methodology_revision_id
                or replay.payload.get("opening_line_kind") != opening_line_kind
                or replay.payload.get("opening_line_evidence_id")
                != requested_quote_evidence_id
                or replay.payload.get("spoiler_policy") != spoiler_policy
                or replay.payload.get("safety_gate", {}).get(
                    "primary_category"
                )
                != resolved_category.value
            ):
                raise IdempotencyConflict(
                    "trial script command key belongs to different inputs"
                )
            return replay

        direction, pack, claims, sources, direction_book_id = (
            self._repository.load_direction_context(direction_revision_id)
        )
        if direction.project_id != project_id or direction_book_id != book_id:
            raise ValueError("selected direction does not belong to project/book")
        methodology = self._repository.get_trial_methodology(
            methodology_revision_id
        )
        if methodology.project_id != project_id:
            raise ValueError("methodology does not belong to project")

        evidence_inputs = tuple(
            TrialEvidenceInput(
                evidence_id=item.id,
                claim_type=item.claim_type,
                normalized_claim=item.normalized_claim,
                spoiler_level=item.spoiler_level,
            )
            for item in claims
            if str(item.id) in set(direction.payload["evidence_ids"])
        )
        source_passages = tuple(
            item.content
            for item in sources
            if item.source_type != "ai_generated"
        )
        direction_material = {
            "direction": direction.payload,
            "claims": [
                {
                    "claim_type": item.claim_type,
                    "normalized_claim": item.normalized_claim,
                    "spoiler_level": item.spoiler_level,
                }
                for item in claims
                if str(item.id) in set(direction.payload["evidence_ids"])
            ],
        }
        safety = TrialSafetyGateService()
        pre_safety = safety.evaluate(
            primary_category=resolved_category,
            phase="pre_compile",
            content_revision_id=f"direction:{direction.id}",
            content=direction_material,
            source_passages=source_passages,
        )
        if pre_safety.blocked_reason_codes:
            raise TrialScriptSafetyBlocked(
                "pre-compile safety gate blocks creative generation: "
                + ",".join(pre_safety.blocked_reason_codes)
            )
        action_request = ActionSkeletonRequest(
            evidence_pack_revision_id=pack.id,
            evidence_pack_digest=pack.digest,
            direction_revision_id=direction.id,
            direction_digest=direction.digest,
            methodology_revision_id=methodology.id,
            methodology_digest=methodology.digest,
            methodology_payload=dict(methodology.payload),
            direction_payload=dict(direction.payload),
            claims=evidence_inputs,
            model_version=self._model_version,
            prompt_version=self._prompt_version,
            primary_safety_category=resolved_category.value,
            safety_cards_manifest_digest=(
                pre_safety.safety_cards_manifest_digest
            ),
            pre_safety_decision_digest=(
                pre_safety.release_decision_digest
            ),
        )
        skeleton = parse_action_skeleton(
            self._transport.generate_action_skeleton(action_request)
        )
        skeleton_payload = skeleton.model_dump(mode="json")
        skeleton_digest = action_skeleton_digest(skeleton_payload)
        narration = parse_narration(
            self._transport.generate_narration(
                NarrationRequest(
                    evidence_pack_revision_id=pack.id,
                    direction_revision_id=direction.id,
                    methodology_revision_id=methodology.id,
                    action_skeleton=skeleton_payload,
                    action_skeleton_digest=skeleton_digest,
                    claims=evidence_inputs,
                    model_version=self._model_version,
                    prompt_version=self._prompt_version,
                    primary_safety_category=resolved_category.value,
                    safety_cards_manifest_digest=(
                        pre_safety.safety_cards_manifest_digest
                    ),
                    pre_safety_decision_digest=(
                        pre_safety.release_decision_digest
                    ),
                )
            )
        )
        narration_payload = narration.model_dump(mode="json")
        payload = {
            "schema_version": TRIAL_SCRIPT_SCHEMA_VERSION,
            "validator_version": TRIAL_VALIDATOR_VERSION,
            "compiler_version": TRIAL_COMPILER_VERSION,
            "model_version": self._model_version,
            "prompt_version": self._prompt_version,
            "project_id": str(project_id),
            "book_id": str(book_id),
            "evidence_pack_revision_id": str(pack.id),
            "resonance_direction_revision_id": str(direction.id),
            "methodology_revision_id": str(methodology.id),
            "methodology_digest": methodology.digest,
            "direction_digest": direction.digest,
            "action_skeleton_digest": skeleton_digest,
            "generation_order": ["action_skeleton", "narration"],
            **skeleton_payload,
            "opening_line": narration_payload["opening_line"],
            "opening_line_kind": opening_line_kind,
            "opening_line_evidence_id": (
                str(verified_quote_evidence_id)
                if verified_quote_evidence_id is not None
                else None
            ),
            "narration_cues": narration_payload["narration_cues"],
            "narration_text": "".join(
                item["text"] for item in narration_payload["narration_cues"]
            ),
            "pronunciation_dictionary": narration_payload[
                "pronunciation_dictionary"
            ],
            "risk_flags": {
                "spoiler": False,
                "copyright": False,
                "factual_conflict": False,
                "pov": False,
            },
            "fit_for": direction.payload["fit_for"],
            "not_fit_for": direction.payload["not_fit_for"],
            "spoiler_level": direction.payload["spoiler_level"],
            "spoiler_policy": spoiler_policy,
        }
        post_safety = safety.evaluate(
            primary_category=resolved_category,
            phase="post_compile",
            content_revision_id=f"script-candidate:{direction.id}",
            content=payload,
            source_passages=source_passages,
        )
        payload["safety_gate"] = TrialScriptSafety(
            primary_category=resolved_category,
            safety_cards_manifest_digest=(
                pre_safety.safety_cards_manifest_digest
            ),
            pre_compile=pre_safety,
            post_compile=post_safety,
        ).model_dump(mode="json")
        canonical = TrialScriptValidator(
            methodology=methodology,
            direction=direction,
            pack=pack,
            claims=claims,
            sources=sources,
            book_id=book_id,
        ).validate(payload)
        return self._repository.store_trial_script(
            StoreTrialScript(
                project_id=project_id,
                book_id=book_id,
                evidence_pack_revision_id=pack.id,
                resonance_direction_revision_id=direction.id,
                methodology_revision_id=methodology.id,
                payload=canonical,
                command_key=command_key,
            )
        )

    def rewrite(
        self,
        *,
        source_trial_script_revision_id: UUID,
        rewritten_payload: Mapping[str, Any],
        command_key: str,
    ) -> TrialScriptRevision:
        """Persist a safety rewrite as a new revision on frozen lineage."""

        (
            source,
            methodology,
            direction,
            pack,
            claims,
            sources,
        ) = self._repository.load_trial_script_context(
            source_trial_script_revision_id
        )
        try:
            source_safety = TrialScriptSafety.model_validate(
                source.payload.get("safety_gate")
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise TrialScriptSafetyBlocked(
                "source trial script safety decision is invalid"
            ) from exc
        if not (
            source_safety.post_compile.blocked_reason_codes
            or source_safety.post_compile.rewrite_requirements
        ):
            raise TrialScriptSafetyBlocked(
                "source trial script does not require a safety rewrite"
            )

        rewritable = {
            "provisional_title",
            "experience_promise",
            "narrator",
            "continuous_moment",
            "primary_conflict",
            "known_now",
            "unknown_now",
            "emotion_curve",
            "shots",
            "opening_line",
            "opening_line_kind",
            "opening_line_evidence_id",
            "narration_cues",
            "narration_text",
            "pronunciation_dictionary",
        }
        if not any(key in rewritten_payload for key in rewritable):
            raise ValueError("safety rewrite contains no script content")
        candidate = deepcopy(source.payload)
        for key in rewritable:
            if key in rewritten_payload:
                candidate[key] = deepcopy(rewritten_payload[key])
        candidate.pop("safety_gate", None)
        candidate.pop("safety_rewrite_provenance", None)
        candidate["action_skeleton_digest"] = action_skeleton_digest(candidate)

        source_passages = tuple(
            item.content
            for item in sources
            if item.source_type != "ai_generated"
        )
        direction_ids = set(direction.payload["evidence_ids"])
        direction_material = {
            "direction": direction.payload,
            "claims": [
                {
                    "claim_type": item.claim_type,
                    "normalized_claim": item.normalized_claim,
                    "spoiler_level": item.spoiler_level,
                }
                for item in claims
                if str(item.id) in direction_ids
            ],
        }
        safety = TrialSafetyGateService()
        pre_safety = safety.evaluate(
            primary_category=source_safety.primary_category,
            phase="pre_compile",
            content_revision_id=f"direction:{direction.id}",
            content=direction_material,
            source_passages=source_passages,
        )
        if pre_safety.blocked_reason_codes:
            raise TrialScriptSafetyBlocked(
                "pre-compile safety gate blocks script rewrite"
            )
        post_safety = safety.evaluate(
            primary_category=source_safety.primary_category,
            phase="post_compile",
            content_revision_id=f"script-candidate:{direction.id}",
            content=candidate,
            source_passages=source_passages,
        )
        candidate["safety_gate"] = TrialScriptSafety(
            primary_category=source_safety.primary_category,
            safety_cards_manifest_digest=(
                pre_safety.safety_cards_manifest_digest
            ),
            pre_compile=pre_safety,
            post_compile=post_safety,
        ).model_dump(mode="json")
        source_decision_digest = (
            source_safety.post_compile.release_decision_digest
        )
        candidate["safety_rewrite_provenance"] = {
            "source_trial_script_revision_id": str(source.id),
            "source_trial_script_digest": source.digest,
            "source_safety_decision_digest": source_decision_digest,
        }
        canonical = TrialScriptValidator(
            methodology=methodology,
            direction=direction,
            pack=pack,
            claims=claims,
            sources=sources,
            book_id=source.book_id,
        ).validate(candidate)
        return self._repository.store_trial_script(
            StoreTrialScript(
                project_id=source.project_id,
                book_id=source.book_id,
                evidence_pack_revision_id=source.evidence_pack_revision_id,
                resonance_direction_revision_id=(
                    source.resonance_direction_revision_id
                ),
                methodology_revision_id=source.methodology_revision_id,
                payload=canonical,
                command_key=command_key,
                source_trial_script_revision_id=source.id,
                source_safety_decision_digest=source_decision_digest,
            )
        )


__all__ = [
    "AICompletedTrialScriptTransport",
    "ActionSkeletonRequest",
    "DeterministicTrialScriptTransport",
    "NarrationRequest",
    "TrialEvidenceInput",
    "TrialScriptCompiler",
    "TrialScriptSafetyBlocked",
    "TrialScriptTransport",
]
