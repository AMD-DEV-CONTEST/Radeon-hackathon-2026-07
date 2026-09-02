from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ModelCredentialRecord


PROVIDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ALGORITHM = "aes-256-gcm-v1"
VerificationStatus = Literal["unchecked", "available", "invalid"]


@dataclass(frozen=True, slots=True)
class SupportedModel:
    provider: str
    provider_label_zh: str
    model_name: str
    label_zh: str
    test_url: str
    official_documentation_url: str
    request_kind: Literal["chat", "image"] = "chat"

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "provider_label": self.provider_label_zh,
            "model_name": self.model_name,
            "label": self.label_zh,
        }


# These are API model identifiers, not marketing names or MCP package versions.
# Keep this catalog intentionally small: task workers resolve credentials by the
# exact same provider/model pair.
SUPPORTED_MODEL_CATALOG = (
    SupportedModel(
        provider="qwen",
        provider_label_zh="阿里云百炼",
        model_name="qwen3.7-plus",
        label_zh="Qwen3.7 Plus（学习分析）",
        test_url=(
            "https://token-plan.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1/"
            "chat/completions"
        ),
        official_documentation_url=(
            "https://help.aliyun.com/zh/model-studio/qwen3-7-plus"
        ),
    ),
    SupportedModel(
        provider="zhipu",
        provider_label_zh="智谱 AI",
        model_name="glm-5.1",
        label_zh="GLM-5.1（拆书/创作）",
        test_url=(
            "https://open.bigmodel.cn/api/coding/paas/v4/"
            "chat/completions"
        ),
        official_documentation_url=(
            "https://docs.bigmodel.cn/cn/guide/models/text/glm-5.1"
        ),
    ),
    SupportedModel(
        provider="zhipu",
        provider_label_zh="智谱 AI",
        model_name="glm-4.6v",
        label_zh="GLM-4.6V（视觉质检）",
        test_url=(
            "https://open.bigmodel.cn/api/paas/v4/"
            "chat/completions"
        ),
        official_documentation_url=(
            "https://docs.bigmodel.cn/cn/guide/models/vlm/glm-4.6v"
        ),
    ),
    SupportedModel(
        provider="zhipu",
        provider_label_zh="智谱 AI",
        model_name="cogview-3-flash",
        label_zh="CogView-3-Flash（图片回退）",
        test_url=(
            "https://open.bigmodel.cn/api/paas/v4/"
            "images/generations"
        ),
        official_documentation_url=(
            "https://docs.bigmodel.cn/cn/guide/models/free/"
            "cogview-3-flash"
        ),
        request_kind="image",
    ),
)
SUPPORTED_MODELS_BY_KEY = {
    (item.provider, item.model_name): item
    for item in SUPPORTED_MODEL_CATALOG
}


class CredentialError(ValueError):
    pass


class CredentialNotFound(CredentialError):
    pass


@dataclass(frozen=True, slots=True)
class CredentialTestResult:
    status: VerificationStatus
    error_code: str | None = None

    @classmethod
    def available(cls) -> "CredentialTestResult":
        return cls(status="available")

    @classmethod
    def invalid(cls, error_code: str) -> "CredentialTestResult":
        return cls(status="invalid", error_code=error_code)

    @classmethod
    def unchecked(cls, error_code: str) -> "CredentialTestResult":
        return cls(status="unchecked", error_code=error_code)


class CredentialConnectionTester(Protocol):
    def test(
        self,
        *,
        provider: str,
        model_name: str,
        api_key: str,
    ) -> CredentialTestResult: ...


CredentialTestTransport = Callable[
    [str, dict[str, str], dict, float],
    int,
]


def _http_test_transport(
    url: str,
    headers: dict[str, str],
    payload: dict,
    timeout: float,
) -> int:
    request = Request(
        url,
        method="POST",
        headers=headers,
        data=json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status)
    except HTTPError as exc:
        try:
            return int(exc.code)
        finally:
            exc.close()


class HttpCredentialConnectionTester:
    """Verify exact model access with a one-output-token request."""

    def __init__(
        self,
        *,
        transport: CredentialTestTransport | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._transport = transport or _http_test_transport
        self._timeout_seconds = timeout_seconds

    def test(
        self,
        *,
        provider: str,
        model_name: str,
        api_key: str,
    ) -> CredentialTestResult:
        try:
            model = supported_model(provider, model_name)
            if model.request_kind == "image":
                payload = {
                    "model": model.model_name,
                    "prompt": "纯白背景中的一个蓝色圆点",
                    "size": "1024x1024",
                }
            else:
                payload = {
                    "model": model.model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": "仅回复 OK",
                        }
                    ],
                    "max_tokens": 1,
                    "stream": False,
                }
                if model.provider == "qwen":
                    payload["enable_thinking"] = False
                else:
                    payload["thinking"] = {"type": "disabled"}
            status_code = self._transport(
                model.test_url,
                {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                payload,
                self._timeout_seconds,
            )
        except (TimeoutError, URLError, OSError):
            return CredentialTestResult.unchecked("provider_unavailable")
        except Exception:
            # Provider response details can contain credential or account data.
            # They are intentionally collapsed into a stable safe code.
            return CredentialTestResult.unchecked("connection_test_failed")

        if 200 <= status_code < 300:
            return CredentialTestResult.available()
        if status_code in (401, 403):
            return CredentialTestResult.invalid("authentication_failed")
        if status_code == 429:
            return CredentialTestResult.invalid("quota_or_rate_limited")
        if 500 <= status_code < 600:
            return CredentialTestResult.unchecked("provider_unavailable")
        return CredentialTestResult.invalid("provider_rejected")


def normalize_provider(value: str) -> str:
    provider = value.strip().lower()
    if not PROVIDER_PATTERN.fullmatch(provider):
        raise CredentialError("提供商名称格式无效。")
    return provider


def normalize_model_name(value: str) -> str:
    model_name = value.strip()
    if (
        not 1 <= len(model_name) <= 200
        or any(ord(character) < 32 or ord(character) == 127 for character in model_name)
    ):
        raise CredentialError("模型名称格式无效。")
    return model_name


def supported_model(provider: str, model_name: str) -> SupportedModel:
    key = (
        normalize_provider(provider),
        normalize_model_name(model_name),
    )
    try:
        return SUPPORTED_MODELS_BY_KEY[key]
    except KeyError:
        raise CredentialError(
            "当前项目不支持该提供商或模型。"
        ) from None


def validate_api_key(value: str) -> str:
    if (
        value != value.strip()
        or not 8 <= len(value) <= 4096
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise CredentialError("API Key 格式无效。")
    return value


def read_master_key(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 64:
            raise OSError
        payload = os.read(descriptor, 65)
    except OSError:
        raise RuntimeError("Creative Hub credential key is unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        key = bytes.fromhex(payload.decode("ascii"))
    except (UnicodeError, ValueError):
        raise RuntimeError("Creative Hub credential key is invalid") from None
    if len(key) != 32:
        raise RuntimeError("Creative Hub credential key is invalid")
    return key


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def _aad(provider: str, model_name: str, key_version: int) -> bytes:
    return (
        f"creative-hub:model-credential:{provider}:{model_name}:v{key_version}"
    ).encode("utf-8")


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    # SQLite drops timezone metadata while PostgreSQL preserves it.
    return value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class CredentialSummary:
    credential_id: UUID
    provider: str
    model_name: str
    key_hint: str
    revision: int
    active: bool
    verification_status: VerificationStatus
    verified_at: datetime | None
    verification_error_code: str | None
    created_at: datetime | None
    updated_at: datetime | None

    def as_dict(self) -> dict:
        return {
            "credential_id": str(self.credential_id),
            "provider": self.provider,
            "model_name": self.model_name,
            "key_hint": self.key_hint,
            "revision": self.revision,
            "active": self.active,
            "verification_status": self.verification_status,
            "verified_at": (
                None
                if self.verified_at is None
                else self.verified_at.isoformat()
            ),
            "verification_error_code": self.verification_error_code,
            "created_at": (
                None
                if self.created_at is None
                else self.created_at.isoformat()
            ),
            "updated_at": (
                None
                if self.updated_at is None
                else self.updated_at.isoformat()
            ),
        }


class CredentialVault:
    """Encrypt model credentials at rest and reveal them only to internal jobs."""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise ValueError("credential master key must contain 32 bytes")
        self._cipher = AESGCM(master_key)

    @classmethod
    def from_file(cls, path: Path) -> "CredentialVault":
        return cls(read_master_key(path))

    @staticmethod
    def _summary(record: ModelCredentialRecord) -> CredentialSummary:
        return CredentialSummary(
            credential_id=record.id,
            provider=record.provider,
            model_name=record.model_name,
            key_hint=record.key_hint,
            revision=record.revision,
            active=record.active,
            verification_status=record.verification_status,
            verified_at=_as_utc(record.verified_at),
            verification_error_code=record.verification_error_code,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def list(self, session: Session) -> tuple[CredentialSummary, ...]:
        records = session.scalars(
            select(ModelCredentialRecord).order_by(
                ModelCredentialRecord.provider.asc(),
                ModelCredentialRecord.model_name.asc(),
            )
        ).all()
        return tuple(self._summary(record) for record in records)

    def put(
        self,
        session: Session,
        *,
        provider: str,
        model_name: str,
        api_key: str,
        actor_id: str,
    ) -> tuple[CredentialSummary, bool]:
        model = supported_model(provider, model_name)
        provider = model.provider
        model_name = model.model_name
        api_key = validate_api_key(api_key)
        record = session.scalar(
            select(ModelCredentialRecord).where(
                ModelCredentialRecord.provider == provider,
                ModelCredentialRecord.model_name == model_name,
            )
        )
        created = record is None
        revision = 1 if record is None else record.revision + 1
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            api_key.encode("utf-8"),
            _aad(provider, model_name, 1),
        )
        fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        if record is None:
            record = ModelCredentialRecord(
                id=uuid4(),
                provider=provider,
                model_name=model_name,
                ciphertext=_encode(ciphertext),
                nonce=_encode(nonce),
                algorithm=ALGORITHM,
                key_version=1,
                key_hint=f"••••{api_key[-4:]}",
                fingerprint=fingerprint,
                revision=revision,
                active=True,
                verification_status="unchecked",
                verified_at=None,
                verification_error_code=None,
                updated_by=actor_id,
            )
            session.add(record)
        else:
            record.ciphertext = _encode(ciphertext)
            record.nonce = _encode(nonce)
            record.algorithm = ALGORITHM
            record.key_version = 1
            record.key_hint = f"••••{api_key[-4:]}"
            record.fingerprint = fingerprint
            record.revision = revision
            record.active = True
            record.verification_status = "unchecked"
            record.verified_at = None
            record.verification_error_code = None
            record.updated_by = actor_id
        session.flush()
        return self._summary(record), created

    def delete(self, session: Session, credential_id: UUID) -> bool:
        record = session.get(ModelCredentialRecord, credential_id)
        if record is None:
            return False
        session.delete(record)
        session.flush()
        return True

    def resolve(
        self,
        session: Session,
        *,
        provider: str,
        model_name: str,
    ) -> tuple[str, int]:
        model = supported_model(provider, model_name)
        provider = model.provider
        model_name = model.model_name
        record = session.scalar(
            select(ModelCredentialRecord).where(
                ModelCredentialRecord.provider == provider,
                ModelCredentialRecord.model_name == model_name,
                ModelCredentialRecord.active.is_(True),
            )
        )
        if record is None:
            raise CredentialNotFound("未配置该提供商和模型的 API Key。")
        if record.algorithm != ALGORITHM or record.key_version != 1:
            raise CredentialError("API Key 加密版本不受支持。")
        try:
            plaintext = self._cipher.decrypt(
                _decode(record.nonce),
                _decode(record.ciphertext),
                _aad(record.provider, record.model_name, record.key_version),
            ).decode("utf-8")
        except Exception:
            raise CredentialError("API Key 密文校验失败。") from None
        if hashlib.sha256(plaintext.encode("utf-8")).hexdigest() != record.fingerprint:
            raise CredentialError("API Key 完整性校验失败。")
        return plaintext, record.revision

    def test_connection(
        self,
        session: Session,
        credential_id: UUID,
        *,
        tester: CredentialConnectionTester,
    ) -> CredentialSummary:
        record = session.get(ModelCredentialRecord, credential_id)
        if record is None or not record.active:
            raise CredentialNotFound("未配置该提供商和模型的 API Key。")
        api_key, _revision = self.resolve(
            session,
            provider=record.provider,
            model_name=record.model_name,
        )
        result = tester.test(
            provider=record.provider,
            model_name=record.model_name,
            api_key=api_key,
        )
        record.verification_status = result.status
        record.verified_at = datetime.now(timezone.utc)
        record.verification_error_code = result.error_code
        session.flush()
        return self._summary(record)
