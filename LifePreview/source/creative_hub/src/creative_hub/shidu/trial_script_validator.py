"""Fail-closed validation for frozen six-shot trial script revisions."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.shidu.schemas import (
    EvidenceClaim,
    EvidencePackRevision,
    ResonanceDirectionRevision,
    SourceDocumentRevision,
    TrialMethodologyRevision,
)
from creative_hub.shidu.trial_methodology import (
    METHODOLOGY_PROMPT_DIGEST,
    METHODOLOGY_VERSION,
    SHOT_BEATS,
    TRIAL_SCRIPT_SCHEMA_VERSION,
    TRIAL_VALIDATOR_VERSION,
    methodology_v01_payload,
)
from creative_hub.shidu.trial_safety import (
    TrialSafetyGateService,
    TrialScriptSafety,
)


TRIAL_COMPILER_VERSION = "shidu-trial-compiler-v1"
_SPOILER_ORDER = {"none": 0, "light": 1, "moderate": 2, "critical": 3}
_FACTUAL_TYPES = {"plot_node", "factual_context"}
_STYLE_TYPES = {"emotional_reaction", "style_judgement", "reader_fit"}
_FORBIDDEN_REVELATIONS = (
    "多年后",
    "后来我才知道",
    "最终我会",
    "结局",
    "谜底",
    "真凶",
    "终极反转",
    "原来一切",
)
_TIME_JUMPS = ("次日", "翌日", "几年后", "几个月后", "多年后", "我的一生")
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


class TrialScriptError(ValueError):
    """The proposed or persisted script violates the frozen methodology."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShotProposal(_StrictModel):
    ordinal: int = Field(ge=1, le=6)
    narrative_task: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=400)
    composition: str = Field(min_length=1, max_length=300)
    camera_movement: str = Field(min_length=1, max_length=200)
    lighting: str = Field(min_length=1, max_length=200)
    sound: str = Field(min_length=1, max_length=200)
    duration_seconds: int = Field(ge=1, le=30)
    state_before: str = Field(min_length=1, max_length=100)
    state_after: str = Field(min_length=1, max_length=100)
    factual_evidence_ids: list[UUID] = Field(min_length=1, max_length=32)
    style_evidence_ids: list[UUID] = Field(min_length=1, max_length=32)


class ActionSkeletonProposal(_StrictModel):
    provisional_title: str = Field(min_length=1, max_length=120)
    experience_promise: str = Field(min_length=1, max_length=300)
    narrator: str = Field(min_length=1, max_length=100)
    continuous_moment: str = Field(min_length=1, max_length=300)
    primary_conflict: str = Field(min_length=1, max_length=300)
    known_now: list[str] = Field(min_length=1, max_length=32)
    unknown_now: list[str] = Field(min_length=1, max_length=32)
    emotion_curve: list[str] = Field(min_length=6, max_length=6)
    shots: list[ShotProposal] = Field(min_length=6, max_length=6)


class NarrationCueProposal(_StrictModel):
    cue_key: str = Field(min_length=1, max_length=80)
    shot_ordinal: int = Field(ge=1, le=6)
    text: str = Field(min_length=1, max_length=500)
    pause_after_ms: int = Field(ge=0, le=5000)
    factual_evidence_ids: list[UUID] = Field(min_length=1, max_length=32)
    style_evidence_ids: list[UUID] = Field(min_length=1, max_length=32)


class NarrationProposal(_StrictModel):
    opening_line: str = Field(min_length=1, max_length=200)
    narration_cues: list[NarrationCueProposal] = Field(
        min_length=6, max_length=6
    )
    pronunciation_dictionary: dict[str, str] = Field(max_length=64)


class _RiskFlags(_StrictModel):
    spoiler: bool
    copyright: bool
    factual_conflict: bool
    pov: bool


class _SafetyRewriteProvenance(_StrictModel):
    source_trial_script_revision_id: UUID
    source_trial_script_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_safety_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class _ScriptPayload(_StrictModel):
    schema_version: str
    validator_version: str
    compiler_version: str
    model_version: str
    prompt_version: str
    project_id: UUID
    book_id: UUID
    evidence_pack_revision_id: UUID
    resonance_direction_revision_id: UUID
    methodology_revision_id: UUID
    methodology_digest: str
    direction_digest: str
    action_skeleton_digest: str
    generation_order: list[str]
    provisional_title: str
    experience_promise: str
    narrator: str
    continuous_moment: str
    primary_conflict: str
    known_now: list[str]
    unknown_now: list[str]
    emotion_curve: list[str]
    shots: list[ShotProposal]
    opening_line: str
    opening_line_kind: Literal["ai_adapted", "verified_quote"]
    opening_line_evidence_id: UUID | None = None
    narration_cues: list[NarrationCueProposal]
    narration_text: str
    pronunciation_dictionary: dict[str, str]
    risk_flags: _RiskFlags
    fit_for: list[dict[str, Any]]
    not_fit_for: list[dict[str, Any]]
    spoiler_level: Literal["none", "light", "moderate", "critical"]
    spoiler_policy: Literal["none", "light", "moderate", "critical"]
    safety_gate: TrialScriptSafety
    safety_rewrite_provenance: _SafetyRewriteProvenance | None = None


def parse_action_skeleton(value: object) -> ActionSkeletonProposal:
    try:
        return ActionSkeletonProposal.model_validate(value)
    except ValidationError as error:
        raise TrialScriptError("action_skeleton structured output is invalid") from error


def parse_narration(value: object) -> NarrationProposal:
    try:
        return NarrationProposal.model_validate(value)
    except ValidationError as error:
        raise TrialScriptError("narration structured output is invalid") from error


def _skeleton_material(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: payload[key]
        for key in (
            "provisional_title",
            "experience_promise",
            "narrator",
            "continuous_moment",
            "primary_conflict",
            "known_now",
            "unknown_now",
            "emotion_curve",
            "shots",
        )
    }


def action_skeleton_digest(payload: Mapping[str, Any]) -> str:
    return canonical_json_digest(_skeleton_material(payload))


def _claim_excerpt(
    claim: EvidenceClaim, source: SourceDocumentRevision
) -> str | None:
    start = claim.source_span.get("start")
    end = claim.source_span.get("end")
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end <= start
        or end > len(source.content)
    ):
        return None
    excerpt = source.content[start:end]
    if hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != claim.excerpt_digest:
        return None
    return excerpt


def _unique_text(values: list[str], label: str) -> tuple[str, ...]:
    canonical = tuple(item.strip() for item in values)
    if any(not item for item in canonical) or len(canonical) != len(set(canonical)):
        raise TrialScriptError(f"knowledge_boundary {label} must be unique")
    return canonical


def _has_grounding_overlap(text: str, basis: tuple[str, ...]) -> bool:
    normalized_text = "".join(_HAN_RE.findall(text))
    if len(normalized_text) < 2:
        return False
    for candidate in basis:
        normalized_basis = "".join(_HAN_RE.findall(candidate))
        if any(
            normalized_basis[index : index + 2] in normalized_text
            for index in range(max(0, len(normalized_basis) - 1))
        ):
            return True
    return False


def _contains_long_source_span(text: str, source: str, *, limit: int = 20) -> bool:
    normalized_text = "".join(text.split())
    normalized_source = "".join(source.split())
    if len(normalized_text) < limit or len(normalized_source) < limit:
        return False
    return any(
        normalized_source[index : index + limit] in normalized_text
        for index in range(len(normalized_source) - limit + 1)
    )


class TrialScriptValidator:
    def __init__(
        self,
        *,
        methodology: TrialMethodologyRevision,
        direction: ResonanceDirectionRevision,
        pack: EvidencePackRevision,
        claims: tuple[EvidenceClaim, ...],
        sources: tuple[SourceDocumentRevision, ...],
        book_id: UUID,
    ) -> None:
        self._methodology = methodology
        self._direction = direction
        self._pack = pack
        self._claims = {item.id: item for item in claims}
        self._sources = {item.id: item for item in sources}
        self._book_id = book_id

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            model = _ScriptPayload.model_validate(payload)
        except ValidationError as error:
            raise TrialScriptError("script_schema is invalid") from error
        canonical = model.model_dump(mode="json", exclude_none=True)
        self._validate_frozen_lineage(model)
        self._validate_methodology(model, canonical)
        self._validate_six_shots(model)
        self._validate_evidence_lineage(model)
        self._validate_narration(model)
        self._validate_opening_line(model)
        self._validate_pronunciation(model)
        if model.risk_flags.model_dump() != {
            "spoiler": False,
            "copyright": False,
            "factual_conflict": False,
            "pov": False,
        }:
            raise TrialScriptError("risk_flags do not match validated truth")
        safety_blocked, safety_exact = self._validate_safety(model, canonical)
        if not safety_blocked or not safety_exact:
            self._validate_knowledge_boundary(model)
            self._validate_copyright(model)
        if not safety_exact:
            raise TrialScriptError("script safety decision is forged or stale")
        return canonical

    def _validate_safety(
        self,
        model: _ScriptPayload,
        canonical: Mapping[str, Any],
    ) -> tuple[bool, bool]:
        manifest = self._methodology.payload.get("safety_cards_manifest")
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("aggregate_digest")
            != model.safety_gate.safety_cards_manifest_digest
        ):
            raise TrialScriptError("safety cards are not frozen by methodology")
        source_passages = tuple(
            item.content
            for item in self._sources.values()
            if item.source_type != "ai_generated"
        )
        direction_material = {
            "direction": self._direction.payload,
            "claims": [
                {
                    "claim_type": item.claim_type,
                    "normalized_claim": item.normalized_claim,
                    "spoiler_level": item.spoiler_level,
                }
                for item in self._claims.values()
                if str(item.id)
                in set(self._direction.payload.get("evidence_ids", ()))
            ],
        }
        service = TrialSafetyGateService()
        expected_pre = service.evaluate(
            primary_category=model.safety_gate.primary_category,
            phase="pre_compile",
            content_revision_id=f"direction:{self._direction.id}",
            content=direction_material,
            source_passages=source_passages,
        )
        post_material = {
            key: value
            for key, value in canonical.items()
            if key not in {"safety_gate", "safety_rewrite_provenance"}
        }
        expected_post = service.evaluate(
            primary_category=model.safety_gate.primary_category,
            phase="post_compile",
            content_revision_id=f"script-candidate:{self._direction.id}",
            content=post_material,
            source_passages=source_passages,
        )
        expected = TrialScriptSafety(
            primary_category=model.safety_gate.primary_category,
            safety_cards_manifest_digest=(
                expected_pre.safety_cards_manifest_digest
            ),
            pre_compile=expected_pre,
            post_compile=expected_post,
        )
        if expected_pre.blocked_reason_codes:
            raise TrialScriptError("pre-compile safety gate blocks script")
        return bool(expected_post.blocked_reason_codes), expected == model.safety_gate

    def _validate_frozen_lineage(self, model: _ScriptPayload) -> None:
        if (
            model.project_id != self._methodology.project_id
            or model.project_id != self._direction.project_id
            or model.project_id != self._pack.project_id
            or model.book_id != self._book_id
            or model.evidence_pack_revision_id != self._pack.id
            or model.resonance_direction_revision_id != self._direction.id
            or model.methodology_revision_id != self._methodology.id
            or model.methodology_digest != self._methodology.digest
            or model.direction_digest != self._direction.digest
        ):
            raise TrialScriptError("frozen_revision_lineage mismatch")
        if self._direction.evidence_pack_revision_id != self._pack.id:
            raise TrialScriptError("frozen_revision_lineage mismatch")
        if not self._pack.publishable:
            raise TrialScriptError("factual_conflict blocks script publication")

    def _validate_methodology(
        self, model: _ScriptPayload, canonical: Mapping[str, Any]
    ) -> None:
        if (
            self._methodology.methodology_version != METHODOLOGY_VERSION
            or self._methodology.prompt_digest != METHODOLOGY_PROMPT_DIGEST
            or self._methodology.validator_version != TRIAL_VALIDATOR_VERSION
            or canonical_json_digest(self._methodology.payload)
            != canonical_json_digest(methodology_v01_payload())
            or model.schema_version != TRIAL_SCRIPT_SCHEMA_VERSION
            or model.validator_version != TRIAL_VALIDATOR_VERSION
            or model.compiler_version != TRIAL_COMPILER_VERSION
            or not model.model_version
            or not model.prompt_version
            or model.generation_order != ["action_skeleton", "narration"]
        ):
            raise TrialScriptError("methodology_revision is invalid")
        if model.action_skeleton_digest != action_skeleton_digest(canonical):
            raise TrialScriptError("action_skeleton digest is invalid")

    @staticmethod
    def _validate_six_shots(model: _ScriptPayload) -> None:
        if len(model.shots) != 6 or [item.ordinal for item in model.shots] != list(
            range(1, 7)
        ):
            raise TrialScriptError("six_shots require ordinals 1 through 6")
        tasks = [str(item["narrative_task"]) for item in SHOT_BEATS]
        if [item.narrative_task for item in model.shots] != tasks:
            raise TrialScriptError("six_shots narrative tasks are invalid")
        transitions = [
            (item.state_before.strip(), item.state_after.strip())
            for item in model.shots
        ]
        if (
            any(not before or not after or before == after for before, after in transitions)
            or len(set(transitions)) != 6
        ):
            raise TrialScriptError("six_shots require six distinct state changes")
        total = 0
        for shot, beat in zip(model.shots, SHOT_BEATS, strict=True):
            expected_before, expected_after = str(
                beat["required_change"]
            ).split("→", 1)
            if (
                shot.state_before != expected_before
                or shot.state_after != expected_after
            ):
                raise TrialScriptError(
                    "six_shots state transition differs from methodology"
                )
            if not (
                int(beat["duration_min_seconds"])
                <= shot.duration_seconds
                <= int(beat["duration_max_seconds"])
            ):
                raise TrialScriptError("six_shots duration is outside methodology")
            total += shot.duration_seconds
        if not 50 <= total <= 70:
            raise TrialScriptError("six_shots total duration is outside methodology")

    @staticmethod
    def _validate_knowledge_boundary(model: _ScriptPayload) -> None:
        known = _unique_text(model.known_now, "known_now")
        unknown = _unique_text(model.unknown_now, "unknown_now")
        if set(known) & set(unknown):
            raise TrialScriptError("knowledge_boundary known and unknown overlap")
        narrative = "\n".join(
            [
                model.opening_line,
                model.continuous_moment,
                model.primary_conflict,
                *(item.action for item in model.shots),
                *(item.text for item in model.narration_cues),
            ]
        )
        if any(item in narrative for item in unknown):
            raise TrialScriptError("knowledge_boundary reveals unknown_now")
        if any(token in narrative for token in _FORBIDDEN_REVELATIONS):
            raise TrialScriptError("knowledge_boundary reveals future or ending")
        if any(token in narrative for token in _TIME_JUMPS):
            raise TrialScriptError("continuous_moment contains a time jump")
        if not all("我" in item.text for item in model.narration_cues):
            raise TrialScriptError("one_narrator must remain first person")

    def _validate_evidence_lineage(self, model: _ScriptPayload) -> None:
        direction_ids = {
            UUID(str(item)) for item in self._direction.payload.get("evidence_ids", ())
        }
        if not direction_ids or not direction_ids.issubset(set(self._pack.evidence_ids)):
            raise TrialScriptError("evidence_lineage direction is invalid")
        items = [*model.shots, *model.narration_cues]
        for item in items:
            factual = tuple(item.factual_evidence_ids)
            style = tuple(item.style_evidence_ids)
            if (
                len(factual) != len(set(factual))
                or len(style) != len(set(style))
                or not set(factual).issubset(direction_ids)
                or not set(style).issubset(direction_ids)
            ):
                raise TrialScriptError("evidence_lineage contains foreign evidence")
            if any(
                evidence_id not in self._claims
                or self._claims[evidence_id].claim_type not in _FACTUAL_TYPES
                for evidence_id in factual
            ):
                raise TrialScriptError("factual evidence_lineage is invalid")
            if any(
                evidence_id not in self._claims
                or self._claims[evidence_id].claim_type not in _STYLE_TYPES
                for evidence_id in style
            ):
                raise TrialScriptError("style evidence_lineage is invalid")
            for evidence_id in (*factual, *style):
                claim = self._claims[evidence_id]
                if claim.source_document_revision_id not in self._sources:
                    raise TrialScriptError("evidence_lineage source is missing")
                if _SPOILER_ORDER[claim.spoiler_level] > _SPOILER_ORDER[
                    model.spoiler_policy
                ]:
                    raise TrialScriptError("spoiler_policy exceeded")
            factual_basis = tuple(
                text
                for evidence_id in factual
                for text in (
                    self._claims[evidence_id].normalized_claim,
                    self._sources[
                        self._claims[evidence_id].source_document_revision_id
                    ].content,
                )
            )
            grounded_text = item.action if isinstance(item, ShotProposal) else item.text
            if not _has_grounding_overlap(grounded_text, factual_basis):
                ordinal = (
                    item.ordinal
                    if isinstance(item, ShotProposal)
                    else item.shot_ordinal
                )
                raise TrialScriptError(
                    f"factual evidence_lineage is ungrounded at shot {ordinal}"
                )
        expected_level = max(
            (self._claims[item].spoiler_level for item in direction_ids),
            key=_SPOILER_ORDER.__getitem__,
        )
        if model.spoiler_level != expected_level:
            raise TrialScriptError("spoiler_level does not match evidence")
        if (
            model.fit_for != self._direction.payload.get("fit_for")
            or model.not_fit_for != self._direction.payload.get("not_fit_for")
        ):
            raise TrialScriptError("reader_fit must come from selected direction")

    def _validate_narration(self, model: _ScriptPayload) -> None:
        if [item.shot_ordinal for item in model.narration_cues] != list(range(1, 7)):
            raise TrialScriptError("narration_cues must map one-to-one to six_shots")
        if len({item.cue_key for item in model.narration_cues}) != 6:
            raise TrialScriptError("narration_cues keys must be unique")
        combined = "".join(item.text for item in model.narration_cues)
        if model.narration_text != combined or not combined.startswith(model.opening_line):
            raise TrialScriptError("narration_text is inconsistent with cues")
        count = len(_HAN_RE.findall(combined))
        if not 180 <= count <= 230:
            raise TrialScriptError("narration_length must contain 180-230 Chinese characters")
    def _validate_opening_line(self, model: _ScriptPayload) -> None:
        if model.opening_line_kind == "ai_adapted":
            if model.opening_line_evidence_id is not None:
                raise TrialScriptError("ai_adapted opening must not claim a quote")
            if any(mark in model.opening_line for mark in ("“", "”", "‘", "’")):
                raise TrialScriptError("ai_adapted opening cannot look like a quote")
            return
        evidence_id = model.opening_line_evidence_id
        claim = self._claims.get(evidence_id) if evidence_id is not None else None
        if claim is None or not claim.is_direct_quote:
            raise TrialScriptError("verified_quote requires direct-quote evidence")
        if evidence_id not in {
            UUID(str(item)) for item in self._direction.payload["evidence_ids"]
        }:
            raise TrialScriptError("verified_quote evidence is outside direction")
        source = self._sources.get(claim.source_document_revision_id)
        excerpt = _claim_excerpt(claim, source) if source is not None else None
        if excerpt != model.opening_line:
            raise TrialScriptError("verified_quote must match exact source span")

    @staticmethod
    def _validate_pronunciation(model: _ScriptPayload) -> None:
        for term, reading in model.pronunciation_dictionary.items():
            if (
                not term.strip()
                or not reading.strip()
                or term not in model.narration_text
                or len(term) > 40
                or len(reading) > 100
            ):
                raise TrialScriptError("pronunciation_dictionary is invalid")

    def _validate_copyright(self, model: _ScriptPayload) -> None:
        surfaces = [
            model.provisional_title,
            model.experience_promise,
            model.narrator,
            model.continuous_moment,
            model.primary_conflict,
            model.opening_line,
            model.narration_text,
            *model.known_now,
            *model.unknown_now,
            *model.emotion_curve,
            *(
                text
                for shot in model.shots
                for text in (
                    shot.narrative_task,
                    shot.action,
                    shot.composition,
                    shot.camera_movement,
                    shot.lighting,
                    shot.sound,
                    shot.state_before,
                    shot.state_after,
                )
            ),
            *(cue.text for cue in model.narration_cues),
            *model.pronunciation_dictionary.keys(),
            *model.pronunciation_dictionary.values(),
            *(
                str(item.get("text", ""))
                for item in (*model.fit_for, *model.not_fit_for)
            ),
        ]
        if any(
            _contains_long_source_span(text, source.content)
            for text in surfaces
            for source in self._sources.values()
            if source.source_type != "ai_generated"
        ):
            raise TrialScriptError("copyright risk from long source passage")


__all__ = [
    "ActionSkeletonProposal",
    "NarrationProposal",
    "ShotProposal",
    "TRIAL_COMPILER_VERSION",
    "TrialScriptError",
    "TrialScriptValidator",
    "action_skeleton_digest",
    "parse_action_skeleton",
    "parse_narration",
]
