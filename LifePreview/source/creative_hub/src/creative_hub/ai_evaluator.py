from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from .evaluations import EvaluationScoreInput, EvaluationSubmission
from .rubric import (
    AI_SHORT_DRAMA_PROFILE_ID,
    EvaluationStage,
    EvaluationSubjectType,
    STAGE_DIMENSIONS,
    frozen_rubric_payload,
)


HUB_AI_PROMPT_VERSION = "hub-ai-short-drama-rubric-v2"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RubricEvidenceInput(StrictModel):
    subject_type: EvaluationSubjectType
    evidence_mode: str = Field(pattern="^(full_video|frames_only)$")
    lineage_group: str = Field(min_length=1, max_length=255)
    synopsis: str = Field(min_length=1, max_length=20_000)
    transcript: str | None = Field(default=None, max_length=40_000)
    evidence_refs: tuple[str, ...] = ()
    known_limitations: tuple[str, ...] = ()
    project_id: str | None = Field(default=None, max_length=255)
    scene_id: str | None = Field(default=None, max_length=255)
    knowledge_pack_version: str | None = Field(default=None, max_length=255)


class RubricModelResponse(StrictModel):
    scores: tuple[EvaluationScoreInput, ...]
    raw_response_ref: str | None = Field(default=None, max_length=500)


class RubricModelClient(Protocol):
    model_name: str
    model_version: str

    def complete_rubric(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


def compile_hub_ai_system_prompt() -> str:
    rubric = frozen_rubric_payload()
    dimensions = {
        item["dimension_id"]: {
            "label": item["label"],
            "description": item["description"],
        }
        for item in rubric["dimensions"]
        if item["dimension_id"]
        in STAGE_DIMENSIONS[EvaluationStage.HUB_AI]
    }
    return (
        "你是 AI 短剧内容评价员。只依据输入证据，按 1–10 整数评分；"
        "证据不足必须输出 score=null、confidence=null，并写 na_reason。"
        "禁止用抽帧推断运动、声音或口型。每个适用维度必须恰好出现一次。"
        "每个维度的 reason 都必须是非空字符串；即使是 N/A，也要简述为何"
        "现有证据不足，并同时填写 na_reason。reason 必须指出可核查依据，"
        "不能泛泛表扬。输出严格 JSON。"
        f"\n量表版本：AI短剧量表 v1\n适用维度：{dimensions}"
    )


class HubAiRubricEvaluator:
    """Compile the frozen rubric and validate a model's structured scores."""

    def __init__(self, client: RubricModelClient) -> None:
        self._client = client

    def evaluate(self, evidence: RubricEvidenceInput) -> EvaluationSubmission:
        response = self._client.complete_rubric(
            system_prompt=compile_hub_ai_system_prompt(),
            payload={
                "subject_type": evidence.subject_type.value,
                "evidence_mode": evidence.evidence_mode,
                "synopsis": evidence.synopsis,
                "transcript": evidence.transcript,
                "evidence_refs": list(evidence.evidence_refs),
                "known_limitations": list(evidence.known_limitations),
            },
        )
        parsed = RubricModelResponse.model_validate(response)
        submission = EvaluationSubmission(
            subject_type=evidence.subject_type,
            scores=parsed.scores,
            evaluator_model=self._client.model_name,
            model_version=self._client.model_version,
            prompt_version=HUB_AI_PROMPT_VERSION,
            raw_response_ref=parsed.raw_response_ref,
            evidence_mode=evidence.evidence_mode,
            profile_id=AI_SHORT_DRAMA_PROFILE_ID,
            lineage_group=evidence.lineage_group,
            project_id=evidence.project_id,
            scene_id=evidence.scene_id,
            knowledge_pack_version=evidence.knowledge_pack_version,
        )
        supplied = {score.dimension_id for score in submission.scores}
        expected = set(STAGE_DIMENSIONS[EvaluationStage.HUB_AI])
        if supplied != expected or len(submission.scores) != len(expected):
            raise ValueError(
                "model response does not contain the exact Hub AI applicability mask"
            )
        if evidence.evidence_mode == "frames_only":
            unobservable = {
                "motion_naturalness",
                "lipsync_quality",
                "audio_technical_quality",
            }
            invalid = [
                score.dimension_id
                for score in submission.scores
                if score.dimension_id in unobservable and score.score is not None
            ]
            if invalid:
                raise ValueError(
                    "model scored dimensions that are unobservable from frames"
                )
        return submission


class OllamaRubricModelClient:
    """Loopback-only structured client for a local, auditable rubric model."""

    def __init__(
        self,
        *,
        model_name: str,
        model_version: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 300,
        audit_dir: str | Path | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Ollama rubric endpoint must be loopback HTTP")
        self.model_name = model_name
        self.model_version = model_version
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.audit_dir = (
            None if audit_dir is None else Path(audit_dir).resolve()
        )

    def _preserve_raw_response(self, content: str) -> str | None:
        if self.audit_dir is None:
            return None
        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        destination = self.audit_dir / f"{digest}.json"
        try:
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            if destination.read_bytes() != encoded:
                raise RuntimeError("Ollama audit response hash collision")
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        return f"local-eval://ollama/{digest}"

    def complete_rubric(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        # Ollama's grammar compiler accepts a deliberately small JSON Schema
        # subset.  Pydantic's generated schema contains defaults, $defs and
        # optional non-required properties that some Ollama builds reject even
        # though the response itself validates correctly.  Keep the generation
        # grammar simple, then apply the full Pydantic validation below.
        score_schema = {
            "type": "object",
            "properties": {
                "dimension_id": {
                    "type": "string",
                    "enum": list(
                        STAGE_DIMENSIONS[EvaluationStage.HUB_AI]
                    ),
                },
                "score": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "maximum": 10,
                },
                "confidence": {
                    "type": ["number", "null"],
                    "minimum": 0,
                    "maximum": 1,
                },
                "reason": {"type": "string", "minLength": 1},
                "na_reason": {
                    "type": ["string", "null"],
                    "minLength": 1,
                },
                "evidence_spans": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "evidence_ref": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "start_ms": {"type": ["integer", "null"]},
                            "end_ms": {"type": ["integer", "null"]},
                            "note": {"type": ["string", "null"]},
                        },
                        "required": [
                            "evidence_ref",
                            "start_ms",
                            "end_ms",
                            "note",
                        ],
                    },
                },
            },
            "required": [
                "dimension_id",
                "score",
                "confidence",
                "reason",
                "na_reason",
                "evidence_spans",
            ],
        }
        response_schema = {
            "type": "object",
            "properties": {
                "scores": {"type": "array", "items": score_schema},
                "raw_response_ref": {"type": ["string", "null"]},
            },
            "required": ["scores", "raw_response_ref"],
        }
        encoded = json.dumps(
            {
                "model": self.model_name,
                "stream": False,
                "format": response_schema,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    },
                ],
                "options": {"temperature": 0},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/chat",
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama rubric request failed ({exc.code}): {detail}"
            ) from exc
        content = envelope.get("message", {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError("Ollama rubric response is incomplete")
        raw_response_ref = self._preserve_raw_response(content)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Ollama rubric response is not valid JSON"
            ) from exc
        validated = RubricModelResponse.model_validate(parsed)
        if raw_response_ref is not None:
            validated = validated.model_copy(
                update={"raw_response_ref": raw_response_ref}
            )
        return validated.model_dump(mode="json")
