"""Strict GLM Vision evaluation boundary for historical identity candidates."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import httpx


_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
_MODEL = "glm-4v-plus"
_PROVIDER = "zhipu"
_SCHEMA_REVISION = "visual-identity-glm-gates.v1"
_PROMPT_REVISION = "visual-identity-historical-candidate.zh.v1"
_POLICY_REVISION = "visual-identity-qualification.v1"
_LICENSE_REUSABLE = frozenset({"public_domain", "licensed_reuse"})
_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_GATE_KEYS = (
    "single_person",
    "face_visible",
    "identity_match",
    "age_match",
    "historical_source_match",
    "watermark_or_text_absent",
    "quality_passed",
)
_GATE_CODES = (
    ("single_person", "MULTIPLE_PERSONS"),
    ("face_visible", "FACE_NOT_VISIBLE"),
    ("identity_match", "IDENTITY_DRIFT"),
    ("age_match", "AGE_MISMATCH"),
    ("historical_source_match", "SOURCE_MISMATCH"),
    ("watermark_or_text_absent", "WATERMARK_OR_TEXT_PRESENT"),
    ("quality_passed", "QUALITY_TOO_LOW"),
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _require_sha256(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_public_text(value: str, field_name: str, *, max_length: int) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a string")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > max_length or any(ord(ch) < 32 for ch in normalized):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def load_api_key_file(path: str | Path) -> str:
    """Explicitly load a caller-selected key file without logging its contents."""

    value = Path(path).read_text(encoding="utf-8").strip()
    if not value or len(value) > 4096 or any(ch.isspace() for ch in value):
        raise ValueError("GLM API key file does not contain one valid key")
    return value


@dataclass(frozen=True, slots=True)
class GlmVisionRequest:
    candidate_id: str
    raw_sha256: str
    sanitized_sha256: str
    mime_type: str
    sanitized_bytes: bytes
    character_name: str
    age_stage: str
    historical_context: str
    license_status: Literal[
        "public_domain", "licensed_reuse", "unknown", "restricted"
    ]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _require_public_text(self.candidate_id, "candidate_id", max_length=128),
        )
        _require_sha256(self.raw_sha256, "raw_sha256")
        _require_sha256(self.sanitized_sha256, "sanitized_sha256")
        if self.mime_type not in _MIME_TYPES:
            raise ValueError("mime_type is not supported")
        if type(self.sanitized_bytes) is not bytes or not self.sanitized_bytes:
            raise ValueError("sanitized_bytes must be non-empty bytes")
        if _sha256(self.sanitized_bytes) != self.sanitized_sha256:
            raise ValueError("sanitized_bytes do not match sanitized_sha256")
        object.__setattr__(
            self,
            "character_name",
            _require_public_text(self.character_name, "character_name", max_length=120),
        )
        object.__setattr__(
            self,
            "age_stage",
            _require_public_text(self.age_stage, "age_stage", max_length=80),
        )
        object.__setattr__(
            self,
            "historical_context",
            _require_public_text(
                self.historical_context,
                "historical_context",
                max_length=1200,
            ),
        )
        if self.license_status not in {
            "public_domain",
            "licensed_reuse",
            "unknown",
            "restricted",
        }:
            raise ValueError("license_status is invalid")


@dataclass(frozen=True, slots=True)
class GlmVisionResult:
    candidate_id: str
    glm_provider: Literal["zhipu"]
    glm_model: Literal["glm-4v-plus"]
    prompt_revision: str
    prompt_sha256: str
    policy_revision: str
    policy_sha256: str
    schema_revision: str
    input_manifest_sha256: str
    request_sha256: str
    response_sha256: str
    single_person: bool
    face_visible: bool
    identity_match: bool
    age_match: bool
    historical_source_match: bool
    watermark_or_text_absent: bool
    quality_passed: bool
    vision_verdict: Literal["passed", "rejected"]
    license_policy_passed: bool
    qualified: bool
    rejection_codes: tuple[str, ...]
    attestation_sha256: str


class GlmVisionRetryableError(RuntimeError):
    """A GLM transport/schema failure; it never counts as candidate rejection."""

    failed_stage = "glm_validation"

    def __init__(self, safe_error_code: str) -> None:
        self.safe_error_code = safe_error_code
        super().__init__(f"GLM vision validation failed: {safe_error_code}")


class ZhipuGlmVisionClient:
    endpoint = _ENDPOINT

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        if type(api_key) is not str or not api_key.strip() or any(ch.isspace() for ch in api_key):
            raise ValueError("api_key must be a non-empty secret string")
        self._api_key = api_key
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(60.0),
            trust_env=False,
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(endpoint={self.endpoint!r}, api_key=<redacted>)"

    def evaluate(self, authority: GlmVisionRequest) -> GlmVisionResult:
        if not isinstance(authority, GlmVisionRequest):
            raise TypeError("authority must be GlmVisionRequest")
        # Re-run invariants before transport even if a frozen object was forged.
        authority = GlmVisionRequest(
            candidate_id=authority.candidate_id,
            raw_sha256=authority.raw_sha256,
            sanitized_sha256=authority.sanitized_sha256,
            mime_type=authority.mime_type,
            sanitized_bytes=authority.sanitized_bytes,
            character_name=authority.character_name,
            age_stage=authority.age_stage,
            historical_context=authority.historical_context,
            license_status=authority.license_status,
        )
        prompt = self._prompt(authority)
        prompt_sha256 = _sha256(prompt.encode("utf-8"))
        policy_payload = {
            "policy_revision": _POLICY_REVISION,
            "gate_keys": _GATE_KEYS,
            "gate_codes": _GATE_CODES,
            "license_reusable": sorted(_LICENSE_REUSABLE),
        }
        policy_sha256 = _canonical_sha256(policy_payload)
        input_manifest = {
            "candidate_id": authority.candidate_id,
            "raw_sha256": authority.raw_sha256,
            "sanitized_sha256": authority.sanitized_sha256,
            "mime_type": authority.mime_type,
            "character_name": authority.character_name,
            "age_stage": authority.age_stage,
            "historical_context": authority.historical_context,
            "license_status": authority.license_status,
            "prompt_sha256": prompt_sha256,
            "policy_sha256": policy_sha256,
        }
        input_manifest_sha256 = _canonical_sha256(input_manifest)
        image_data = base64.b64encode(authority.sanitized_bytes).decode("ascii")
        payload = {
            "model": _MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{authority.mime_type};base64,{image_data}"
                            },
                        },
                    ],
                }
            ],
        }
        request_sha256 = _canonical_sha256(payload)
        try:
            response = self._client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                ),
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise GlmVisionRetryableError("transport_failure") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise GlmVisionRetryableError("provider_unavailable")
        if response.status_code != 200 or response.history:
            raise GlmVisionRetryableError("provider_response_invalid")
        response_sha256 = _sha256(response.content)
        gates = self._parse_gates(response)
        rejection_codes = tuple(code for key, code in _GATE_CODES if not gates[key])
        vision_passed = not rejection_codes
        license_passed = authority.license_status in _LICENSE_REUSABLE
        if not license_passed:
            rejection_codes = (*rejection_codes, "LICENSE_NOT_REUSABLE")
        result_payload = {
            "candidate_id": authority.candidate_id,
            "glm_provider": _PROVIDER,
            "glm_model": _MODEL,
            "prompt_revision": _PROMPT_REVISION,
            "prompt_sha256": prompt_sha256,
            "policy_revision": _POLICY_REVISION,
            "policy_sha256": policy_sha256,
            "schema_revision": _SCHEMA_REVISION,
            "input_manifest_sha256": input_manifest_sha256,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
            **gates,
            "vision_verdict": "passed" if vision_passed else "rejected",
            "license_policy_passed": license_passed,
            "qualified": vision_passed and license_passed,
            "rejection_codes": rejection_codes,
        }
        return GlmVisionResult(
            **result_payload,
            attestation_sha256=_canonical_sha256(result_payload),
        )

    @staticmethod
    def _prompt(authority: GlmVisionRequest) -> str:
        return (
            "你是历史人物参考图核验器。只核验输入图片，不推断版权或补写史实。"
            f"目标人物：{authority.character_name}；目标年龄阶段：{authority.age_stage}；"
            f"冻结历史语境：{authority.historical_context}。"
            "必须只返回一个 JSON object，且恰好包含以下七个 boolean 字段："
            "single_person, face_visible, identity_match, age_match, "
            "historical_source_match, watermark_or_text_absent, quality_passed。"
            "禁止解释、Markdown、附加字段或字符串布尔值。"
        )

    @staticmethod
    def _parse_gates(response: httpx.Response) -> dict[str, bool]:
        try:
            envelope = response.json()
            if not isinstance(envelope, dict) or "choices" not in envelope:
                raise TypeError("envelope")
            choices = envelope["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise TypeError("choices")
            choice = choices[0]
            if not isinstance(choice, dict):
                raise TypeError("choice")
            message = choice.get("message")
            if not isinstance(message, dict):
                raise TypeError("message")
            content = message.get("content")
            if not isinstance(content, str):
                raise TypeError("content")
            gates = json.loads(content)
            if not isinstance(gates, dict) or set(gates) != set(_GATE_KEYS):
                raise TypeError("gates")
            if any(type(gates[key]) is not bool for key in _GATE_KEYS):
                raise TypeError("gate type")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GlmVisionRetryableError("provider_schema_invalid") from exc
        return {key: gates[key] for key in _GATE_KEYS}


__all__ = [
    "GlmVisionRequest",
    "GlmVisionResult",
    "GlmVisionRetryableError",
    "ZhipuGlmVisionClient",
    "load_api_key_file",
]

