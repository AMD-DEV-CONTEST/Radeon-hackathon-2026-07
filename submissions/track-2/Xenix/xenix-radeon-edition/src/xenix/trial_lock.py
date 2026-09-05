from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from .config import AppPaths
from .release_config import load_release_config

TRIAL_LOCK_STATE_FILE_NAME = "trial_lock.json"
TRIAL_LOCK_SCHEMA_VERSION = 1
def trial_purchase_url() -> str:
    return load_release_config().trial_purchase_url


class TrialLockReason(StrEnum):
    DISABLED = "disabled"
    FIRST_RUN = "first_run"
    ACTIVE = "active"
    EXPIRED = "expired"
    CLOCK_ROLLBACK = "clock_rollback"
    TAMPERED = "tampered"


@dataclass(frozen=True)
class PackagedTrialLockConfig:
    days: int = 0
    state_secret: str = ""
    build_id: str = "development"

    def __post_init__(self) -> None:
        if self.days < 0:
            raise ValueError("Trial lock days cannot be negative.")
        if self.days > 0 and not self.state_secret:
            raise ValueError("Trial lock state secret is required when the lock is enabled.")

    @property
    def enabled(self) -> bool:
        return self.days > 0


@dataclass(frozen=True)
class TrialLockCheck:
    enabled: bool
    locked: bool
    reason: TrialLockReason
    state_path: Path
    first_seen_utc: datetime | None = None
    last_seen_utc: datetime | None = None
    expires_at_utc: datetime | None = None


@dataclass(frozen=True)
class _TrialLockState:
    first_seen_utc: datetime
    last_seen_utc: datetime
    build_id: str


class TrialLockStateError(ValueError):
    pass


def trial_lock_state_path(paths: AppPaths) -> Path:
    return paths.state / TRIAL_LOCK_STATE_FILE_NAME


def load_packaged_trial_lock_config() -> PackagedTrialLockConfig:
    config = load_release_config()
    return PackagedTrialLockConfig(
        days=config.trial_lock_days,
        state_secret=config.trial_lock_state_secret,
        build_id=config.trial_lock_build_id,
    )


def check_trial_lock(
    paths: AppPaths,
    *,
    now: datetime | None = None,
    config: PackagedTrialLockConfig | None = None,
) -> TrialLockCheck:
    resolved_config = config or load_packaged_trial_lock_config()
    state_path = trial_lock_state_path(paths)
    if not resolved_config.enabled:
        return TrialLockCheck(
            enabled=False,
            locked=False,
            reason=TrialLockReason.DISABLED,
            state_path=state_path,
        )

    now_utc = _normalize_utc(now or datetime.now(UTC))
    if not state_path.exists():
        state = _TrialLockState(
            first_seen_utc=now_utc,
            last_seen_utc=now_utc,
            build_id=resolved_config.build_id,
        )
        _write_state(state_path, state, resolved_config)
        return TrialLockCheck(
            enabled=True,
            locked=False,
            reason=TrialLockReason.FIRST_RUN,
            state_path=state_path,
            first_seen_utc=state.first_seen_utc,
            last_seen_utc=state.last_seen_utc,
            expires_at_utc=_expires_at(state, resolved_config),
        )

    try:
        state = _read_state(state_path, resolved_config)
    except (OSError, json.JSONDecodeError, TrialLockStateError, ValueError):
        return TrialLockCheck(
            enabled=True,
            locked=True,
            reason=TrialLockReason.TAMPERED,
            state_path=state_path,
        )

    expires_at = _expires_at(state, resolved_config)
    if now_utc < state.last_seen_utc:
        return TrialLockCheck(
            enabled=True,
            locked=True,
            reason=TrialLockReason.CLOCK_ROLLBACK,
            state_path=state_path,
            first_seen_utc=state.first_seen_utc,
            last_seen_utc=state.last_seen_utc,
            expires_at_utc=expires_at,
        )

    if now_utc >= expires_at:
        return TrialLockCheck(
            enabled=True,
            locked=True,
            reason=TrialLockReason.EXPIRED,
            state_path=state_path,
            first_seen_utc=state.first_seen_utc,
            last_seen_utc=state.last_seen_utc,
            expires_at_utc=expires_at,
        )

    updated_state = _TrialLockState(
        first_seen_utc=state.first_seen_utc,
        last_seen_utc=max(state.last_seen_utc, now_utc),
        build_id=resolved_config.build_id,
    )
    if updated_state != state:
        _write_state(state_path, updated_state, resolved_config)
    return TrialLockCheck(
        enabled=True,
        locked=False,
        reason=TrialLockReason.ACTIVE,
        state_path=state_path,
        first_seen_utc=updated_state.first_seen_utc,
        last_seen_utc=updated_state.last_seen_utc,
        expires_at_utc=expires_at,
    )


def _expires_at(state: _TrialLockState, config: PackagedTrialLockConfig) -> datetime:
    return state.first_seen_utc + timedelta(days=config.days)


def _read_state(path: Path, config: PackagedTrialLockConfig) -> _TrialLockState:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TrialLockStateError("Trial lock state payload must be an object.")
    signature = str(payload.get("signature") or "")
    unsigned_payload = {key: value for key, value in payload.items() if key != "signature"}
    expected_signature = _sign_state_payload(unsigned_payload, config)
    if not signature or not hmac.compare_digest(signature, expected_signature):
        raise TrialLockStateError("Trial lock state signature is invalid.")

    if payload.get("schema_version") != TRIAL_LOCK_SCHEMA_VERSION:
        raise TrialLockStateError("Trial lock state schema is unsupported.")
    first_seen_utc = _parse_utc(payload.get("first_seen_utc"))
    last_seen_utc = _parse_utc(payload.get("last_seen_utc"))
    if last_seen_utc < first_seen_utc:
        raise TrialLockStateError("Trial lock state timestamps are inconsistent.")
    return _TrialLockState(
        first_seen_utc=first_seen_utc,
        last_seen_utc=last_seen_utc,
        build_id=str(payload.get("build_id") or ""),
    )


def _write_state(
    path: Path,
    state: _TrialLockState,
    config: PackagedTrialLockConfig,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": TRIAL_LOCK_SCHEMA_VERSION,
        "build_id": state.build_id,
        "first_seen_utc": _format_utc(state.first_seen_utc),
        "last_seen_utc": _format_utc(state.last_seen_utc),
    }
    payload["signature"] = _sign_state_payload(payload, config)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sign_state_payload(payload: dict[str, Any], config: PackagedTrialLockConfig) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    serialized = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(config.state_secret.encode("utf-8"), serialized, hashlib.sha256).hexdigest()


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).replace(microsecond=0)
    return value.astimezone(UTC).replace(microsecond=0)


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TrialLockStateError("Trial lock timestamp is missing.")
    raw_value = value.strip()
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrialLockStateError("Trial lock timestamp is invalid.") from exc
    return _normalize_utc(parsed)


def _format_utc(value: datetime) -> str:
    return _normalize_utc(value).isoformat().replace("+00:00", "Z")
