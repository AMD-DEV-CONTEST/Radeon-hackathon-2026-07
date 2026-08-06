from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


POLICY_VERSION = "prooflaunch-api-guardrails-2026-08-02.v1"
SCHEMA = "ProofLaunchProductionGuardrailDecisionV1"
LEDGER_SCHEMA = "ProofLaunchProductionGuardrailEventV1"
_GENESIS_HASH = "0" * 64
_DIRECTIONS = frozenset({"input", "output"})

_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:prior|previous|above)\s+instructions?\b", re.I),
    re.compile(r"\b(?:reveal|print|exfiltrate|leak)\s+(?:the\s+)?(?:system|developer|hidden)\s+(?:prompt|message|instructions?)\b", re.I),
    re.compile(r"\b(?:bypass|disable|override)\s+(?:the\s+)?(?:policy|guardrail|safety|approval)\b", re.I),
    re.compile(r"\bCONTEXT_CANARY_IGNORE_ALL_PRIOR_INSTRUCTIONS\b", re.I),
)
_EMAIL = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w-])", re.I)
_PHONE = re.compile(r"(?<!\w)(\+?\d[\d ()-]{7,}\d)(?!\w)")
_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|rk|pk|ghp|github_pat|xox[baprs])-[_A-Za-z0-9]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}\b", re.I),
)
_SYNTHETIC_EMAIL_SUFFIXES = (".test", ".invalid", ".example")


class GuardrailBlockedError(ValueError):
    """A request or response crossed a code-enforced content boundary."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _string_leaves(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _string_leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _string_leaves(item)


def _email_hits(text: str) -> int:
    count = 0
    for match in _EMAIL.finditer(text):
        address = match.group(1).casefold()
        if address.endswith(_SYNTHETIC_EMAIL_SUFFIXES):
            continue
        count += 1
    return count


def _phone_hits(text: str) -> int:
    count = 0
    for match in _PHONE.finditer(text):
        candidate = match.group(1)
        digits = re.sub(r"\D", "", candidate)
        if 8 <= len(digits) <= 15 and (
            candidate.startswith("+")
            or " " in candidate
            or "-" in candidate
            or "(" in candidate
        ):
            count += 1
    return count


@dataclass(frozen=True)
class GuardrailDecision:
    direction: str
    route: str
    content_sha256: str
    text_field_count: int
    hit_counts: Mapping[str, int]
    blocked_categories: tuple[str, ...]
    schema_valid: bool

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_categories) or not self.schema_valid

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "policy_version": POLICY_VERSION,
            "direction": self.direction,
            "route": self.route,
            "content_sha256": self.content_sha256,
            "text_field_count": self.text_field_count,
            "hit_counts": dict(self.hit_counts),
            "blocked": self.blocked,
            "blocked_categories": list(self.blocked_categories),
            "schema_valid": self.schema_valid,
            "raw_content_retained": False,
        }


def evaluate_guardrails(
    payload: Any,
    *,
    direction: str,
    route: str,
    schema_valid: bool = True,
) -> GuardrailDecision:
    if direction not in _DIRECTIONS:
        raise ValueError("guardrail direction must be input or output")
    if not isinstance(route, str) or not route.startswith("/") or len(route) > 512:
        raise ValueError("guardrail route must be a bounded absolute API path")
    canonical = _canonical(payload)
    leaves = tuple(_string_leaves(payload))
    counts = {"prompt_injection": 0, "pii_email": 0, "pii_phone": 0, "secret": 0}
    for text in leaves:
        counts["prompt_injection"] += sum(
            len(pattern.findall(text)) for pattern in _INJECTION_PATTERNS
        )
        counts["pii_email"] += _email_hits(text)
        counts["pii_phone"] += _phone_hits(text)
        counts["secret"] += sum(
            len(pattern.findall(text)) for pattern in _SECRET_PATTERNS
        )

    blocked: list[str] = []
    if not schema_valid:
        blocked.append("schema")
    if direction == "input":
        blocked.extend(category for category, count in counts.items() if count > 0)
    elif counts["secret"] > 0:
        blocked.append("secret")
    return GuardrailDecision(
        direction=direction,
        route=route,
        content_sha256=_sha256_text(canonical),
        text_field_count=len(leaves),
        hit_counts=counts,
        blocked_categories=tuple(sorted(set(blocked))),
        schema_valid=schema_valid,
    )


class GuardrailTelemetryLedger:
    """Append-only, content-free guardrail telemetry with a verified hash chain."""

    def __init__(self, root: Path, *, retention_days: int = 90) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("guardrail ledger root must be an absolute pathlib.Path")
        if type(retention_days) is not int or not 30 <= retention_days <= 90:
            raise ValueError("guardrail retention_days must be in [30, 90]")
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise ValueError("guardrail ledger root must be a real directory")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        self.root = root.resolve(strict=True)
        self.path = self.root / "events.jsonl"
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise ValueError("guardrail ledger path must be a regular file")
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        self.path.chmod(0o600)
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._events = self._load_verified()

    def _load_verified(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        previous = _GENESIS_HASH
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"guardrail ledger line {line_number} is invalid JSON"
                ) from error
            if not isinstance(event, dict) or event.get("schema") != LEDGER_SCHEMA:
                raise ValueError("guardrail ledger schema is invalid")
            supplied = event.get("event_hash")
            unsigned = dict(event)
            unsigned.pop("event_hash", None)
            expected = _sha256_text(_canonical(unsigned))
            if event.get("sequence") != line_number:
                raise ValueError("guardrail ledger sequence drifted")
            if event.get("previous_hash") != previous or supplied != expected:
                raise ValueError("guardrail ledger hash chain is invalid")
            if event.get("raw_content_retained") is not False:
                raise ValueError("guardrail ledger retained raw content")
            previous = str(supplied)
            events.append(event)
        return events

    def append(
        self,
        decision: GuardrailDecision,
        *,
        tenant_id: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            previous = self._events[-1]["event_hash"] if self._events else _GENESIS_HASH
            event: dict[str, Any] = {
                "schema": LEDGER_SCHEMA,
                "sequence": len(self._events) + 1,
                "occurred_at": _utc_now(),
                "policy_version": POLICY_VERSION,
                "retention_days": self.retention_days,
                "tenant_principal_sha256": (
                    _sha256_text(tenant_id) if tenant_id is not None else None
                ),
                "direction": decision.direction,
                "route": decision.route,
                "content_sha256": decision.content_sha256,
                "text_field_count": decision.text_field_count,
                "hit_counts": dict(decision.hit_counts),
                "blocked": decision.blocked,
                "blocked_categories": list(decision.blocked_categories),
                "schema_valid": decision.schema_valid,
                "raw_content_retained": False,
                "previous_hash": previous,
            }
            event["event_hash"] = _sha256_text(_canonical(event))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical(event) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._events.append(event)
            return dict(event)

    def status(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            tenant_digest = _sha256_text(tenant_id) if tenant_id is not None else None
            selected = [
                event
                for event in self._events
                if tenant_digest is None
                or event.get("tenant_principal_sha256") == tenant_digest
            ]
            input_events = [event for event in selected if event["direction"] == "input"]
            output_events = [event for event in selected if event["direction"] == "output"]
            blocked = [event for event in selected if event["blocked"]]
            category_hits = {
                category: sum(
                    int(event["hit_counts"].get(category, 0)) for event in selected
                )
                for category in ("prompt_injection", "pii_email", "pii_phone", "secret")
            }
            return {
                "schema": "ProofLaunchProductionGuardrailStatusV1",
                "policy_version": POLICY_VERSION,
                "retention_days": self.retention_days,
                "event_count": len(selected),
                "input_event_count": len(input_events),
                "output_event_count": len(output_events),
                "blocked_event_count": len(blocked),
                "category_hit_counts": category_hits,
                "hash_chain_valid": True,
                "latest_event_hash": (
                    selected[-1]["event_hash"] if selected else _GENESIS_HASH
                ),
                "raw_content_retained": False,
                "production_deployment_observed": False,
            }


__all__ = [
    "GuardrailBlockedError",
    "GuardrailDecision",
    "GuardrailTelemetryLedger",
    "LEDGER_SCHEMA",
    "POLICY_VERSION",
    "SCHEMA",
    "evaluate_guardrails",
]
