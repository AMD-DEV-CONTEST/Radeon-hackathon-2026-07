"""Safe local-model configuration wizard.

Writes a local-model config to an approved location. Default behavior:
``enabled=False`` and ``dry_run_default=True`` — writing the config
never opens live calls. Network providers, unpinned ids, stale ids,
unknown providers, unsupported task classes, and paths outside the
approved config root are all blocked with specific status tokens.

The wizard performs no model invocation. It writes JSON to disk only
inside the supplied ``config_root``.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .live_model_admission import _LOCAL_PROVIDERS, _NETWORK_PROVIDER_TOKENS
from .local_model_admission_policy import ModelProvider
from .local_model_config_record import (
    LOCAL_MODEL_CONFIG_STATUS_TOKENS,
    LocalModelConfigRecord,
)
from .model_router import CURRENT_MODEL_IDS, STALE_MODEL_IDS, TaskClass

_DEFAULT_STALE_AFTER_DAYS = 180


@dataclass(frozen=True)
class WizardConfig:
    config_root: Path
    allowed_task_classes: frozenset[str] = field(
        default_factory=lambda: frozenset(t.value for t in TaskClass if t is not TaskClass.UNKNOWN)
    )


class LocalModelConfigWizard:
    """Stateless config-writer. Same inputs → same record."""

    def __init__(self, config: WizardConfig) -> None:
        self._config = config

    def write_config(
        self,
        *,
        provider: str,
        model_id: str,
        model_digest_or_revision: str = "",
        capabilities: Iterable[str] = (),
        task_classes_allowed: Iterable[str] = (),
        network_required: bool = False,
        enabled: bool = False,  # default OFF
        dry_run_default: bool = True,  # default ON
    ) -> LocalModelConfigRecord:
        capabilities_t = tuple(c for c in capabilities if c)
        task_classes_t = tuple(t for t in task_classes_allowed if t)

        # 1. Unknown provider.
        if provider not in _LOCAL_PROVIDERS and provider not in _NETWORK_PROVIDER_TOKENS:
            return self._blocked(
                provider,
                model_id,
                capabilities_t,
                task_classes_t,
                "LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER",
                f"provider {provider!r} not recognized",
                network_required=network_required,
            )

        # 2. Network provider blocked outright.
        if provider in _NETWORK_PROVIDER_TOKENS:
            return self._blocked(
                provider,
                model_id,
                capabilities_t,
                task_classes_t,
                "LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER",
                f"provider {provider!r} is a network provider",
                network_required=True,
            )

        # 3. Stale id.
        if model_id in STALE_MODEL_IDS:
            return self._blocked(
                provider,
                model_id,
                capabilities_t,
                task_classes_t,
                "LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID",
                f"model_id {model_id!r} is in STALE_MODEL_IDS",
                network_required=network_required,
            )

        # 4. Unpinned id (except no_model).
        if provider != ModelProvider.NO_MODEL.value and model_id not in CURRENT_MODEL_IDS:
            return self._blocked(
                provider,
                model_id,
                capabilities_t,
                task_classes_t,
                "LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL",
                f"model_id {model_id!r} not pinned in CURRENT_MODEL_IDS",
                network_required=network_required,
            )

        # 5. Task-class overlap (skip for no_model).
        if provider != ModelProvider.NO_MODEL.value:
            overlap = set(task_classes_t) & self._config.allowed_task_classes
            if not overlap:
                return self._blocked(
                    provider,
                    model_id,
                    capabilities_t,
                    task_classes_t,
                    "LOCAL_MODEL_CONFIG_BLOCKED_UNSUPPORTED_TASK_CLASS",
                    "no overlap with allowed task classes",
                    network_required=network_required,
                )

        # 6. Config-root validity.
        try:
            root = self._config.config_root.resolve()
        except (OSError, RuntimeError) as exc:
            return self._blocked(
                provider,
                model_id,
                capabilities_t,
                task_classes_t,
                "LOCAL_MODEL_CONFIG_BLOCKED_INVALID_LOCATION",
                f"config_root resolve failed: {exc}",
                network_required=network_required,
            )

        # 7. Write JSON file (bounded to config_root).
        now = _dt.datetime.now(_dt.UTC)
        stale = now + _dt.timedelta(days=_DEFAULT_STALE_AFTER_DAYS)
        rec = LocalModelConfigRecord(
            provider=provider,
            model_id=model_id,
            model_digest_or_revision=model_digest_or_revision,
            capabilities=capabilities_t,
            task_classes_allowed=task_classes_t,
            network_required=network_required,
            local_only=(not network_required),
            enabled=enabled,
            dry_run_default=dry_run_default,
            created_at=now.isoformat(),
            stale_after=stale.isoformat(),
            decision=(
                "LOCAL_MODEL_CONFIG_DRY_RUN_ONLY" if not enabled else "LOCAL_MODEL_CONFIG_WRITTEN"
            ),
            config_path="",  # filled below
            notes=("dry_run_default=True; enabled requires explicit caller opt-in",),
        )

        # File name keyed on model_id (sanitized).
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in model_id)
        target = root / f"{safe_name or 'local_model'}.json"
        root.mkdir(parents=True, exist_ok=True)
        target.write_text(rec.to_json(), encoding="utf-8")
        return _with_config_path(rec, str(target))

    @staticmethod
    def _blocked(
        provider: str,
        model_id: str,
        capabilities: tuple[str, ...],
        task_classes: tuple[str, ...],
        decision: str,
        reason: str,
        *,
        network_required: bool,
    ) -> LocalModelConfigRecord:
        now = _dt.datetime.now(_dt.UTC).isoformat()
        return LocalModelConfigRecord(
            provider=provider,
            model_id=model_id,
            model_digest_or_revision="",
            capabilities=capabilities,
            task_classes_allowed=task_classes,
            network_required=network_required,
            local_only=(not network_required),
            enabled=False,
            dry_run_default=True,
            created_at=now,
            stale_after=now,
            decision=decision,
            config_path="",
            notes=(reason,),
        )


def _with_config_path(rec: LocalModelConfigRecord, p: str) -> LocalModelConfigRecord:
    return LocalModelConfigRecord(
        provider=rec.provider,
        model_id=rec.model_id,
        model_digest_or_revision=rec.model_digest_or_revision,
        capabilities=rec.capabilities,
        task_classes_allowed=rec.task_classes_allowed,
        network_required=rec.network_required,
        local_only=rec.local_only,
        enabled=rec.enabled,
        dry_run_default=rec.dry_run_default,
        created_at=rec.created_at,
        stale_after=rec.stale_after,
        decision=rec.decision,
        config_path=p,
        notes=rec.notes,
    )


__all__ = [
    "LocalModelConfigWizard",
    "WizardConfig",
    "LocalModelConfigRecord",
    "LOCAL_MODEL_CONFIG_STATUS_TOKENS",
]
