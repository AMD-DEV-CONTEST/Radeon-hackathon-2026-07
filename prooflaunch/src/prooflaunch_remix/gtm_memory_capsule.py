from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from .gtm_learning_memory import (
    LearningMemoryError,
    validate_project_learning_context,
)
from .ledger import canonical_json


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MemoryCapsuleError(ValueError):
    pass


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise MemoryCapsuleError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MemoryCapsuleError(f"{field} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise MemoryCapsuleError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise MemoryCapsuleError(f"{field} must be a safe bounded identifier")
    return value


def _secret(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise MemoryCapsuleError("memory capsule signing secret must be at least 32 bytes")
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def issue_memory_capsule(
    context: Mapping[str, object],
    *,
    tenant_id: str,
    project_id: str,
    signing_secret: bytes,
    key_id: str = "local-session-v1",
    issued_at: datetime | None = None,
    ttl_seconds: int = 86_400,
    nonce: str | None = None,
) -> dict[str, object]:
    tenant = _identifier(tenant_id, "tenant_id")
    project = _identifier(project_id, "project_id")
    key = _identifier(key_id, "key_id")
    secret = _secret(signing_secret)
    if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 2_592_000:
        raise MemoryCapsuleError("ttl_seconds must be between 60 and 2592000")
    try:
        admitted_context = validate_project_learning_context(context)
    except LearningMemoryError as error:
        raise MemoryCapsuleError(f"learning context is invalid: {error}") from error
    issued = (issued_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    nonce_value = nonce or secrets.token_hex(16)
    if not re.fullmatch(r"[0-9a-f]{32}", nonce_value):
        raise MemoryCapsuleError("nonce must contain 32 lowercase hexadecimal characters")
    core: dict[str, object] = {
        "schema": "ProofLaunchPortableMemoryCapsuleV1",
        "tenant_id": tenant,
        "project_id": project,
        "key_id": key,
        "issued_at": _iso(issued),
        "expires_at": _iso(issued + timedelta(seconds=ttl_seconds)),
        "nonce": nonce_value,
        "context": admitted_context,
        "context_sha256": admitted_context["context_sha256"],
        "automatic_strategy_mutation_authorized": False,
        "automatic_external_action_authorized": False,
        "human_review_required_after_import": True,
    }
    capsule_sha256 = _digest(core)
    signature = hmac.new(
        secret, canonical_json(core).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        **core,
        "capsule_id": f"capsule-{capsule_sha256[:24]}",
        "capsule_sha256": capsule_sha256,
        "signature_algorithm": "hmac-sha256",
        "signature": signature,
    }


def verify_memory_capsule(
    capsule: object,
    *,
    signing_secret: bytes,
    expected_tenant_id: str,
    expected_project_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    if not isinstance(capsule, Mapping):
        raise MemoryCapsuleError("memory capsule must be an object")
    expected_keys = {
        "schema",
        "tenant_id",
        "project_id",
        "key_id",
        "issued_at",
        "expires_at",
        "nonce",
        "context",
        "context_sha256",
        "automatic_strategy_mutation_authorized",
        "automatic_external_action_authorized",
        "human_review_required_after_import",
        "capsule_id",
        "capsule_sha256",
        "signature_algorithm",
        "signature",
    }
    if set(capsule) != expected_keys:
        raise MemoryCapsuleError("memory capsule schema keys are invalid")
    if capsule.get("schema") != "ProofLaunchPortableMemoryCapsuleV1":
        raise MemoryCapsuleError("memory capsule schema is unsupported")
    tenant = _identifier(capsule.get("tenant_id"), "tenant_id")
    project = _identifier(capsule.get("project_id"), "project_id")
    if tenant != _identifier(expected_tenant_id, "expected_tenant_id"):
        raise MemoryCapsuleError("memory capsule belongs to another tenant")
    if expected_project_id is not None and project != _identifier(
        expected_project_id, "expected_project_id"
    ):
        raise MemoryCapsuleError("memory capsule belongs to another project")
    if capsule.get("automatic_strategy_mutation_authorized") is not False:
        raise MemoryCapsuleError("memory capsule cannot authorize strategy mutation")
    if capsule.get("automatic_external_action_authorized") is not False:
        raise MemoryCapsuleError("memory capsule cannot authorize external action")
    if capsule.get("human_review_required_after_import") is not True:
        raise MemoryCapsuleError("memory capsule lost the import review gate")
    if capsule.get("signature_algorithm") != "hmac-sha256":
        raise MemoryCapsuleError("memory capsule signature algorithm is unsupported")
    context = capsule.get("context")
    try:
        admitted_context = validate_project_learning_context(context)
    except LearningMemoryError as error:
        raise MemoryCapsuleError(f"memory capsule context is invalid: {error}") from error
    if capsule.get("context_sha256") != admitted_context["context_sha256"]:
        raise MemoryCapsuleError("memory capsule context digest disagrees")
    core = {key: capsule[key] for key in capsule if key not in {
        "capsule_id", "capsule_sha256", "signature_algorithm", "signature"
    }}
    observed_sha256 = _digest(core)
    if capsule.get("capsule_sha256") != observed_sha256:
        raise MemoryCapsuleError("memory capsule content digest failed")
    if capsule.get("capsule_id") != f"capsule-{observed_sha256[:24]}":
        raise MemoryCapsuleError("memory capsule identity failed")
    signature = capsule.get("signature")
    if not isinstance(signature, str) or not _SHA256.fullmatch(signature):
        raise MemoryCapsuleError("memory capsule signature is malformed")
    expected_signature = hmac.new(
        _secret(signing_secret), canonical_json(core).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise MemoryCapsuleError("memory capsule signature failed")
    issued = _parse_iso(capsule.get("issued_at"), "issued_at")
    expires = _parse_iso(capsule.get("expires_at"), "expires_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expires <= issued or current >= expires:
        raise MemoryCapsuleError("memory capsule is expired")
    if issued > current + timedelta(minutes=5):
        raise MemoryCapsuleError("memory capsule issuance is in the future")
    return dict(capsule)


def merge_project_learning_contexts(
    contexts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    memories_by_id: dict[str, dict[str, object]] = {}
    for context in contexts:
        try:
            admitted = validate_project_learning_context(context)
        except LearningMemoryError as error:
            raise MemoryCapsuleError(f"learning context is invalid: {error}") from error
        for item in admitted["memories"]:
            memory_id = str(item["memory_id"])
            current = memories_by_id.get(memory_id)
            normalized = dict(item)
            if current is not None and current != normalized:
                raise MemoryCapsuleError(
                    "conflicting portable memories share one immutable identity"
                )
            memories_by_id[memory_id] = normalized
    memories = sorted(
        memories_by_id.values(),
        key=lambda item: (str(item["approved_at"]), str(item["memory_id"])),
    )
    result: dict[str, object] = {
        "schema": "ProofLaunchProjectLearningContextV1",
        "memory_count": len(memories),
        "memories": memories,
        "latest_next_cycle_decision": memories[-1]["next_cycle_decision"] if memories else None,
        "latest_source_observation_id": memories[-1]["observation_id"] if memories else None,
        "human_promoted_only": True,
        "automatic_strategy_mutation_executed": False,
        "human_review_required_before_application": True,
        "truth_boundary": (
            "This immutable snapshot merges native and separately reviewed portable aggregate "
            "learnings. It excludes raw creative and audience identifiers, and cannot mutate "
            "strategy or authorize an external action."
        ),
    }
    result["context_sha256"] = _digest(result)
    return result
